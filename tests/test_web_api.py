"""Tests for the web layer that exposes the desktop features.

The app runs against the SQLite fallback here (no MariaDB, no network): the
environment is pointed away from MariaDB before ``server`` is imported, so
these tests exercise registration, settings, sync guards, prompts, history,
search and export without touching a database server, Garmin or any AI
provider.
"""

import os
import sys
import tempfile
from uuid import uuid4

import pytest

# Must be set before garmin_db is imported, so no MariaDB pool is attempted.
os.environ["MARIADB_HOST"] = ""
os.environ["MARIADB_PASSWORD"] = ""
os.environ.setdefault("HEALTHCHAT_BASE_URL", "http://testserver")

fastapi_testclient = pytest.importorskip("fastapi.testclient")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import server  # noqa: E402
import web_workspace  # noqa: E402

PASSWORD = "correct-horse-battery"


@pytest.fixture(autouse=True)
def _no_mariadb(monkeypatch):
    """Keep these tests on the SQLite fallback, whatever the machine holds.

    ``load_db_env`` copies ~/.healthchat/db.env over the environment on every
    ``GarminDatabase()``, so clearing the variables is not enough: on a machine
    that has real credentials there, each instantiation would spend its connect
    timeout reaching for a database these tests must not touch. Stubbing the
    loader keeps the run hermetic and fast.
    """
    import garmin_db

    monkeypatch.setattr(garmin_db, "load_db_env", lambda: None)
    monkeypatch.setenv("MARIADB_HOST", "")
    monkeypatch.setenv("MARIADB_PASSWORD", "")


@pytest.fixture
def client():
    return fastapi_testclient.TestClient(server.app)


@pytest.fixture
def account(client):
    """A registered, logged-in account."""
    email = f"web-{uuid4().hex[:10]}@example.com"
    response = client.post(
        "/api/auth/register",
        json={"email": email, "password": PASSWORD, "sex": "male",
              "height_cm": 182, "age": 50, "weight_kg": 88},
    )
    assert response.status_code == 200, response.text
    return client


def _workspace():
    session = list(server._active_sessions.values())[-1]
    return web_workspace.get_workspace(session)


# --- access control ---------------------------------------------------------


@pytest.mark.parametrize("path", ["/api/settings", "/api/status", "/api/prompts", "/api/chats"])
def test_endpoints_require_a_session(client, path):
    assert client.get(path).status_code == 401


# --- settings ---------------------------------------------------------------


def test_settings_expose_the_whole_desktop_config(account):
    config = account.get("/api/settings").json()["config"]

    for key in ("ai_provider", "garmin_email", "ollama_base_url", "strava_client_id"):
        assert key in config


def test_secrets_never_reach_the_browser(account):
    account.post("/api/settings", json={"values": {"garmin_password": "topsecret", "xai_api_key": "sk-test"}})

    config = account.get("/api/settings").json()["config"]

    assert "garmin_password" not in config
    assert "xai_api_key" not in config
    assert config["secrets_set"]["garmin_password"] is True
    assert config["secrets_set"]["xai_api_key"] is True


def test_blank_secret_keeps_the_stored_value(account):
    account.post("/api/settings", json={"values": {"anthropic_api_key": "sk-keep"}})
    account.post("/api/settings", json={"values": {"anthropic_api_key": ""}})

    assert account.get("/api/settings").json()["config"]["secrets_set"]["anthropic_api_key"] is True


def test_unknown_settings_keys_are_ignored(account):
    account.post("/api/settings", json={"values": {"not_a_setting": "x", "garmin_email": "a@b.se"}})

    config = account.get("/api/settings").json()["config"]

    assert "not_a_setting" not in config
    assert config["garmin_email"] == "a@b.se"


def test_settings_survive_a_new_workspace(account):
    """Settings are stored, not just held in memory."""
    account.post("/api/settings", json={"values": {"garmin_email": "persist@example.com"}})
    workspace = _workspace()
    web_workspace.drop_workspace(workspace.user_id)

    assert account.get("/api/settings").json()["config"]["garmin_email"] == "persist@example.com"


# --- connection status and sync guards --------------------------------------


def test_status_reports_every_source(account):
    payload = account.get("/api/status").json()

    assert payload["sources"] == {"garmin": False, "fitbit": False, "withings": False, "strava": False}
    assert payload["authenticated"] is False


def test_checkin_without_a_connected_source_is_refused(account):
    response = account.post("/api/checkin", json={"full": False, "days": 30})

    assert response.status_code == 400
    assert "inte ansluten" in response.json()["detail"].lower()


def test_checkin_rejects_an_unknown_source(account):
    assert account.post("/api/checkin", json={"source": "whoop"}).status_code == 404


def test_garmin_connect_requires_credentials(account):
    assert account.post("/api/garmin/connect").status_code == 400


def test_mfa_requires_six_digits(account):
    assert account.post("/api/garmin/mfa", json={"code": "123"}).status_code == 400


def test_refresh_requires_a_garmin_connection(account):
    assert account.post("/api/refresh").status_code == 400


# --- OAuth ------------------------------------------------------------------


def test_oauth_url_requires_a_client_id(account):
    assert account.get("/api/connect/strava/url").status_code == 400


def test_oauth_url_uses_the_server_redirect(account):
    account.post("/api/settings", json={"values": {"fitbit_client_id": "ABC123"}})

    payload = account.get("/api/connect/fitbit/url").json()

    assert "fitbit.com" in payload["url"]
    assert payload["redirect_uri"].endswith("/oauth/fitbit/callback")


def test_oauth_callback_without_a_code_shows_an_error_page(client):
    response = client.get("/oauth/withings/callback")

    assert response.status_code == 200
    assert "Ingen kod" in response.text


def test_unknown_oauth_service_is_rejected(account):
    assert account.get("/api/connect/whoop/url").status_code == 404


def test_unknown_import_source_is_rejected(account):
    response = account.post("/api/import/whoop", files={"file": ("x.csv", b"a,b\n1,2")})

    assert response.status_code == 404


# --- quick questions and prompts --------------------------------------------


def test_quick_questions_default_to_the_desktop_set(account):
    questions = account.get("/api/quick-questions").json()["questions"]

    assert questions == web_workspace.DEFAULT_QUICK_QUESTIONS


def test_quick_questions_are_trimmed_and_capped(account):
    saved = account.post("/api/quick-questions", json={"questions": [f"q{i}" for i in range(12)] + ["", "  "]})

    assert saved.json()["questions"] == [f"q{i}" for i in range(8)]


def test_prompt_crud(account):
    assert account.post("/api/prompts", json={"name": "A", "prompt": "p"}).json()["prompts"]
    assert account.put("/api/prompts/0", json={"name": "B", "prompt": "p2"}).json()["prompts"][0]["name"] == "B"
    assert account.delete("/api/prompts/0").json()["prompts"] == []
    assert account.delete("/api/prompts/5").status_code == 404


# --- conversation, history, search and export -------------------------------


def _seed_conversation():
    workspace = _workspace()
    workspace.add_message("Du", "Hur ser min sömn ut?", "user")
    workspace.add_message("HealthChat", "**Sömn** var bra.", "assistant")
    return workspace


def test_chat_requires_an_api_key(account):
    response = account.post("/api/chat", json={"message": "Hur mår jag?"})

    assert response.status_code == 400
    assert "API-nyckel" in response.json()["detail"]


def test_save_load_rename_and_delete_a_conversation(account):
    _seed_conversation()

    chat_id = account.post("/api/chats", json={"name": "Test"}).json()["chat"]["id"]
    assert len(account.get("/api/chats").json()["chats"]) == 1
    assert len(account.post(f"/api/chats/{chat_id}/load").json()["messages"]) == 2
    assert account.put(f"/api/chats/{chat_id}", json={"name": "Ny"}).json()["chats"][0]["name"] == "Ny"
    assert account.delete(f"/api/chats/{chat_id}").json()["chats"] == []


def test_saving_an_empty_conversation_is_refused(account):
    _workspace().reset_chat()

    assert account.post("/api/chats", json={"name": "Tom"}).status_code == 400


def test_an_unknown_chat_id_is_not_found(account):
    assert account.get("/api/chats/does-not-exist").status_code == 404


def test_search_finds_the_current_conversation(account):
    _seed_conversation()

    results = account.get("/api/search?q=sömn").json()["results"]

    assert results and results[0]["chat"] == "Nuvarande chatt"


def test_reset_clears_the_conversation(account):
    _seed_conversation()

    assert account.post("/api/chat/reset").json()["messages"] == []


@pytest.mark.parametrize("fmt, magic", [("txt", b"GARMIN"), ("pdf", b"%PDF"), ("docx", b"PK")])
def test_export_produces_each_format(account, fmt, magic):
    _seed_conversation()

    response = account.post("/api/export", json={"format": fmt})

    assert response.status_code == 200
    assert response.content.startswith(magic)


def test_export_rejects_an_unknown_format(account):
    _seed_conversation()

    assert account.post("/api/export", json={"format": "rtf"}).status_code == 400


# --- dashboard and zones ----------------------------------------------------


def test_dashboard_returns_the_series_the_charts_need(account):
    payload = account.get("/api/dashboard/summary?days=30").json()

    for key in ("daily_summary", "sleep", "body_battery", "stress", "hrv", "activities",
                "body_composition", "calorie_burn"):
        assert key in payload["history"], key
    assert "calorie_burn_today" in payload


def test_hr_zones_come_from_the_profile(account):
    payload = account.get("/api/hr-zones").json()

    assert len(payload["zones"]["zones"]) == 5
    assert payload["zones"]["max_hr"] > 0


# --- profile routes the frontend calls --------------------------------------


def test_profile_update_is_served_on_the_path_the_frontend_uses(account):
    response = account.post("/api/user/profile", json={"weight_kg": 86.5})

    assert response.status_code == 200
    assert response.json()["profile"]["weight_kg"] == 86.5


def test_password_change_is_served_on_the_path_the_frontend_uses(account):
    response = account.post("/api/user/password", json={"current_password": "wrong", "new_password": PASSWORD})

    # Reachable (not a 404) and refuses the wrong current password.
    assert response.status_code in (400, 401)


# --- account isolation ------------------------------------------------------


def test_two_accounts_do_not_share_settings_or_prompts(account):
    account.post("/api/settings", json={"values": {"garmin_email": "first@example.com"}})
    account.post("/api/prompts", json={"name": "Mine", "prompt": "Analysera"})

    other = fastapi_testclient.TestClient(server.app)
    other.post("/api/auth/register",
               json={"email": f"web-{uuid4().hex[:10]}@example.com", "password": PASSWORD})

    assert other.get("/api/settings").json()["config"]["garmin_email"] == ""
    assert other.get("/api/prompts").json()["prompts"] == []
