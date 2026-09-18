"""
Unit tests for HealthChat FastAPI Web Server (server.py).
Tests REST authentication endpoints, session cookies, dashboard queries, and SSE chat endpoints.
"""

import json
import pytest
import auth
from garmin_db import GarminDatabase
from fastapi.testclient import TestClient
import server
from server import app, _active_sessions

client = TestClient(app, base_url="https://testserver")


def test_root_endpoint_serves_html():
    """Test root GET / returns 200 OK HTML response."""
    response = client.get("/")
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]


def test_auth_me_unauthorized_without_cookie():
    """Test GET /api/auth/me returns 401 Unauthorized when not logged in."""
    response = client.get("/api/auth/me")
    assert response.status_code == 401


def test_register_login_and_me_flow(monkeypatch):
    """Test user registration, login, get_me, and logout flow via API."""
    test_email = "webtestuser@example.com"
    test_password = "password12345"

    dummy_session = auth.UserSession(
        user_id=99,
        email=test_email,
        dek=bytearray(b"0123456789abcdef0123456789abcdef"),
        encrypted_profile={"sex": "male", "age": 28, "height_cm": 180.0, "weight_kg": 75.0}
    )

    monkeypatch.setattr("server.get_db_conn", lambda db: None)
    monkeypatch.setattr("auth.register_user", lambda conn, email, pwd, initial_profile: (99, "REC-KEY-123", dummy_session))
    monkeypatch.setattr("auth.authenticate_user", lambda conn, email, pwd: dummy_session)

    # Register
    reg_payload = {
        "email": test_email,
        "password": test_password,
        "sex": "male",
        "age": 28,
        "height_cm": 180.0,
        "weight_kg": 75.0
    }
    reg_res = client.post("/api/auth/register", json=reg_payload)
    assert reg_res.status_code == 200, reg_res.text
    reg_data = reg_res.json()
    assert reg_data["status"] == "success"
    assert reg_data["recovery_key"] == "REC-KEY-123"
    assert "healthchat_session" in reg_res.cookies

    # Get Me with session cookie
    me_res = client.get("/api/auth/me", cookies=reg_res.cookies)
    assert me_res.status_code == 200
    me_data = me_res.json()
    assert me_data["email"] == test_email
    assert me_data["profile"]["height_cm"] == 180.0

    # Test update profile
    update_res = client.post(
        "/api/profile/update",
        json={"sex": "female", "age": 30, "height_cm": 175.0, "weight_kg": 68.0, "waist_cm": 78.5, "resting_hr": 55.0, "max_hr": 185.0, "training_goals": "Milen under 45 min och öka muskelmassa", "injuries": "Känning i höger hälsena"},
        cookies=reg_res.cookies
    )
    assert update_res.status_code == 200
    assert update_res.json()["profile"]["weight_kg"] == 68.0
    assert update_res.json()["profile"]["waist_cm"] == 78.5
    assert update_res.json()["profile"]["resting_hr"] == 55.0
    assert update_res.json()["profile"]["max_hr"] == 185.0
    assert update_res.json()["profile"]["training_goals"] == "Milen under 45 min och öka muskelmassa"
    assert update_res.json()["profile"]["injuries"] == "Känning i höger hälsena"

    # Test fetch external profile endpoint
    fetch_ext_res = client.get("/api/user/profile/fetch_external", cookies=reg_res.cookies)
    assert fetch_ext_res.status_code == 200
    assert fetch_ext_res.json()["status"] == "success"

    # Verify updated profile via /api/auth/me
    me_updated = client.get("/api/auth/me", cookies=reg_res.cookies)
    assert me_updated.status_code == 200
    assert me_updated.json()["profile"]["weight_kg"] == 68.0
    assert me_updated.json()["profile"]["waist_cm"] == 78.5
    assert me_updated.json()["profile"]["age"] == 30
    assert me_updated.json()["profile"]["training_goals"] == "Milen under 45 min och öka muskelmassa"
    assert me_updated.json()["profile"]["injuries"] == "Känning i höger hälsena"

    # Test rotate recovery key
    monkeypatch.setattr("auth.rotate_recovery_key", lambda conn, uid, pwd: "NEW-REC-KEY-999")
    rot_res = client.post("/api/user/rotate_recovery_key", json={"current_password": test_password}, cookies=reg_res.cookies)
    assert rot_res.status_code == 200
    assert rot_res.json()["new_recovery_key"] == "NEW-REC-KEY-999"

    # Test delete account
    monkeypatch.setattr("auth.delete_user_account", lambda conn, uid: True)
    del_res = client.delete("/api/user/delete_account", cookies=reg_res.cookies)
    assert del_res.status_code == 200
    assert del_res.json()["status"] == "success"

    # Logout
    logout_res = client.post("/api/auth/logout", cookies=reg_res.cookies)
    assert logout_res.status_code == 200

    # Verify Unauthorized after logout
    after_me_res = client.get("/api/auth/me")
    assert after_me_res.status_code == 401


def test_dashboard_summary_with_missing_weight_uses_fallback(monkeypatch, tmp_path):
    """B-3: When weight is missing in profile and body_comp has no weight, default 70kg is used."""
    test_email = "bmrtest@example.com"
    dummy_session = auth.UserSession(
        user_id=101,
        email=test_email,
        dek=bytearray(b"0123456789abcdef0123456789abcdef"),
        encrypted_profile={"sex": "male", "age": 40, "height_cm": 180.0, "weight_kg": None}
    )

    test_db = GarminDatabase(db_path=tmp_path / "test_bmr.db")
    # Insert a body comp row without weight_kg
    test_db.upsert_body_composition({"date": "2026-09-11", "muscle_mass_kg": 50.0})

    from server import get_current_session
    app.dependency_overrides[get_current_session] = lambda: dummy_session
    monkeypatch.setattr("server.bind_user_db", lambda *args, **kwargs: test_db)
    monkeypatch.setattr("server.get_db_conn", lambda *args, **kwargs: None)

    try:
        res = client.get("/api/dashboard/summary")
        assert res.status_code == 200
        data = res.json()
        assert "calorie_burn_today" in data
        # Full day BMR with 70kg fallback: 10*70 + 6.25*180 - 5*40 + 5 = 1630
        assert data["calorie_burn_today"]["bmr_full"] > 1000
        assert data["calorie_burn_today"]["bmr_source"] == "mifflin"
    finally:
        app.dependency_overrides.pop(get_current_session, None)


def test_ai_chat_sse_stream_format(monkeypatch, tmp_path):
    """B-1: Verify that /api/ai/chat returns SSE stream with {"chunk": ...} and {"done": true}."""
    test_email = "chattest@example.com"
    dummy_session = auth.UserSession(
        user_id=102,
        email=test_email,
        dek=bytearray(b"0123456789abcdef0123456789abcdef"),
        encrypted_profile={"sex": "male", "age": 35, "training_goals": "Bli starkare i marklyft och springa milen", "injuries": "Känning i höger hälsena"}
    )

    test_db = GarminDatabase(db_path=tmp_path / "test_chat.db")

    captured = {}
    def mock_chat(self, *args, **kwargs):
        captured["provider"] = self.provider
        captured["model"] = self.model
        captured["ollama_base_url"] = getattr(self, "ollama_base_url", None)
        captured["garmin_context"] = kwargs.get("garmin_context")
        return "Det här är ett AI-svar med åäö."

    from server import get_current_session
    app.dependency_overrides[get_current_session] = lambda: dummy_session
    monkeypatch.setattr("server.bind_user_db", lambda *args, **kwargs: test_db)
    monkeypatch.setattr("server.get_db_conn", lambda *args, **kwargs: None)
    monkeypatch.setattr("server.AIClient.chat", mock_chat)

    try:
        res = client.post(
            "/api/ai/chat",
            json={
                "message": "Hur mår jag?",
                "weather_context": "Göteborg: +14°C (Halvklart), Vind 3 m/s, Nederbörd 0.0 mm. Fina förhållanden för utomhuspass!"
            }
        )
        assert res.status_code == 200
        assert "text/event-stream" in res.headers["content-type"]
        body = res.text
        chunks = []
        for line in body.split("\n"):
            line = line.strip()
            if line.startswith("data: "):
                parsed = json.loads(line[6:])
                if "chunk" in parsed:
                    chunks.append(parsed["chunk"])
        reassembled = "".join(chunks)
        assert reassembled == "Det här är ett AI-svar med åäö."
        assert "ett AI-svar" in reassembled
        assert captured["provider"] == "ollama"
        assert "192.168.107.15:11436" in captured["ollama_base_url"]
        assert captured["model"] in ("gemma4:12b", "qwen2.5:latest")
        assert "🎯 MÅL MED TRÄNINGEN: Bli starkare i marklyft och springa milen" in captured["garmin_context"]
        assert "⚠️ KÄNDA SKADOR / FYSISKA BEGRÄNSNINGAR: Känning i höger hälsena" in captured["garmin_context"]
        assert "⛅ AKTUELLT LOKALT VÄDER: Göteborg: +14°C" in captured["garmin_context"]
    finally:
        app.dependency_overrides.pop(get_current_session, None)


def test_chart_js_static_served():
    """Verify that local Chart.js bundle is served from /static/chart.umd.min.js and loaded in index.html."""
    res_static = client.get("/static/chart.umd.min.js")
    assert res_static.status_code == 200
    assert len(res_static.content) > 100_000
    assert b"Chart" in res_static.content

    res_root = client.get("/")
    assert res_root.status_code == 200
    assert "/static/chart.umd.min.js" in res_root.text


def test_auth_me_with_bearer_token():
    """Verify that Authorization: Bearer <session_id> authenticates successfully without cookies."""
    import server
    test_sid = "test-bearer-token-12345"
    test_session = auth.UserSession(
        user_id=123,
        email="bearer@example.com",
        dek=bytearray(b"0123456789abcdef0123456789abcdef"),
        encrypted_profile={"sex": "female", "age": 35}
    )
    server.store_active_session(test_sid, test_session)
    try:
        res = client.get("/api/auth/me", headers={"Authorization": f"Bearer {test_sid}"})
        assert res.status_code == 200
        data = res.json()
        assert data["user_id"] == 123
        assert data["email"] == "bearer@example.com"
        assert data["profile"]["sex"] == "female"
    finally:
        server.remove_active_session(test_sid)


def test_ai_chat_history_and_clear():
    """Verify that chat history can be retrieved and cleared via API."""
    import server
    test_sid = "test-chat-history-session-999"
    test_session = auth.UserSession(
        user_id=999,
        email="historytest@example.com",
        dek=bytearray(b"0123456789abcdef0123456789abcdef"),
        encrypted_profile={"sex": "male", "age": 30}
    )
    server.store_active_session(test_sid, test_session)
    # Populate mock history
    server._session_chat_histories[test_sid] = [
        {"role": "user", "content": "Hej!"},
        {"role": "assistant", "content": "Hej! Hur kan jag hjälpa dig?"}
    ]
    server._user_chat_histories[999] = list(server._session_chat_histories[test_sid])

    try:
        # 1. Fetch history
        res = client.get("/api/ai/chat/history", headers={"Authorization": f"Bearer {test_sid}"}, cookies={"healthchat_session": test_sid})
        assert res.status_code == 200
        data = res.json()
        assert "history" in data
        assert len(data["history"]) == 2
        assert data["history"][0]["content"] == "Hej!"

        # 2. Clear history
        res_clear = client.post("/api/ai/chat/clear", headers={"Authorization": f"Bearer {test_sid}"}, cookies={"healthchat_session": test_sid})
        assert res_clear.status_code == 200
        assert res_clear.json()["status"] == "cleared"

        # 3. Verify history is empty
        res_after = client.get("/api/ai/chat/history", headers={"Authorization": f"Bearer {test_sid}"}, cookies={"healthchat_session": test_sid})
        assert res_after.status_code == 200
        assert res_after.json()["history"] == []
    finally:
        server.remove_active_session(test_sid)


def test_preload_ai_endpoint_and_login_trigger(monkeypatch):
    """Verify that /api/ai/preload endpoint works and login triggers preload."""
    test_sid = "preload-test-token"
    test_session = auth.UserSession(
        user_id=888,
        email="preload@example.com",
        dek=bytearray(b"0123456789abcdef0123456789abcdef"),
        encrypted_profile={}
    )
    server.store_active_session(test_sid, test_session)

    preload_called = []
    monkeypatch.setattr(
        "ai_client.preload_ollama_model",
        lambda *args, **kwargs: preload_called.append(True) or True
    )

    try:
        # 1. Test explicit /api/ai/preload endpoint
        res = client.post(
            "/api/ai/preload",
            headers={"Authorization": f"Bearer {test_sid}"},
            cookies={"healthchat_session": test_sid}
        )
        assert res.status_code == 200
        assert res.json()["status"] == "success"

        # 2. Test trigger_model_preload directly
        server._last_preload_time = 0.0
        server.trigger_model_preload()
        assert len(preload_called) >= 1
    finally:
        server.remove_active_session(test_sid)


def test_get_weather_endpoint(monkeypatch):
    """Verify that /api/weather returns weather data and advice."""
    test_sid = "weather-test-token"
    test_session = auth.UserSession(
        user_id=777,
        email="weather@example.com",
        dek=bytearray(b"0123456789abcdef0123456789abcdef"),
        encrypted_profile={}
    )
    server.store_active_session(test_sid, test_session)

    class DummyResponse:
        def __init__(self, status_code, data):
            self.status_code = status_code
            self._data = data
        def json(self):
            return self._data

    def mock_requests_get(url, timeout=5):
        if "open-meteo" in url:
            return DummyResponse(200, {
                "current": {
                    "temperature_2m": 15.5,
                    "apparent_temperature": 15.0,
                    "wind_speed_10m": 4.2,
                    "precipitation": 0.0,
                    "weather_code": 1,
                    "relative_humidity_2m": 60
                },
                "hourly": {
                    "precipitation_probability": [5]
                }
            })
        elif "reverse-geocode" in url:
            return DummyResponse(200, {"city": "Göteborg"})
        elif "ip-api" in url:
            return DummyResponse(200, {"city": "Göteborg", "lat": 57.70, "lon": 11.97})
        return DummyResponse(404, {})

    monkeypatch.setattr("requests.get", mock_requests_get)

    try:
        res = client.get(
            "/api/weather?lat=57.70&lon=11.97",
            headers={"Authorization": f"Bearer {test_sid}"},
            cookies={"healthchat_session": test_sid}
        )
        assert res.status_code == 200
        data = res.json()
        assert data["status"] == "success"
        assert data["locationName"] == "Göteborg"
        assert data["temp"] == 15.5
        assert data["wind"] == 4.2
        assert "Mestadels klart" in data["weatherDesc"]
        assert "Fina förhållanden" in data["advice"]
    finally:
        server.remove_active_session(test_sid)

