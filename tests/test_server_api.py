"""
Unit tests for HealthChat FastAPI Web Server (server.py).
Tests REST authentication endpoints, session cookies, dashboard queries, and SSE chat endpoints.
"""

import pytest
import auth
from garmin_db import GarminDatabase
from fastapi.testclient import TestClient
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
        json={"sex": "female", "age": 30, "height_cm": 175.0, "weight_kg": 68.0, "resting_hr": 55.0, "max_hr": 185.0},
        cookies=reg_res.cookies
    )
    assert update_res.status_code == 200
    assert update_res.json()["profile"]["weight_kg"] == 68.0
    assert update_res.json()["profile"]["resting_hr"] == 55.0
    assert update_res.json()["profile"]["max_hr"] == 185.0

    # Test fetch external profile endpoint
    fetch_ext_res = client.get("/api/user/profile/fetch_external", cookies=reg_res.cookies)
    assert fetch_ext_res.status_code == 200
    assert fetch_ext_res.json()["status"] == "success"

    # Verify updated profile via /api/auth/me
    me_updated = client.get("/api/auth/me", cookies=reg_res.cookies)
    assert me_updated.status_code == 200
    assert me_updated.json()["profile"]["weight_kg"] == 68.0
    assert me_updated.json()["profile"]["age"] == 30

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
        encrypted_profile={"sex": "male", "age": 35}
    )

    test_db = GarminDatabase(db_path=tmp_path / "test_chat.db")

    from server import get_current_session
    app.dependency_overrides[get_current_session] = lambda: dummy_session
    monkeypatch.setattr("server.bind_user_db", lambda *args, **kwargs: test_db)
    monkeypatch.setattr("server.get_db_conn", lambda *args, **kwargs: None)
    monkeypatch.setattr("server.AIClient.chat", lambda self, *args, **kwargs: "Det här är ett AI-svar med åäö.")

    try:
        res = client.post("/api/ai/chat", json={"message": "Hur mår jag?", "provider": "openai"})
        assert res.status_code == 200
        assert "text/event-stream" in res.headers["content-type"]
        body = res.text
        assert '{"chunk":' in body
        assert '{"done": true}' in body
        assert "åäö" in body
    finally:
        app.dependency_overrides.pop(get_current_session, None)



