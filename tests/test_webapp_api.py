"""Tests for the HealthChat web API.

The app is imported after pointing ``HEALTHCHAT_DATA_DIR`` at a throwaway
directory, so accounts, databases and tokens created here never touch a real
deployment. No test performs a network call: Garmin, the AI providers and the
OAuth exchanges are never reached.
"""

import os
import tempfile

import pytest

os.environ["HEALTHCHAT_DATA_DIR"] = tempfile.mkdtemp(prefix="healthchat-test-")

fastapi_testclient = pytest.importorskip("fastapi.testclient")

from webapp.backend.main import app  # noqa: E402
from webapp.backend.workspace import DEFAULT_QUICK_QUESTIONS  # noqa: E402

PASSWORD = "correct-horse-battery"


@pytest.fixture
def client():
    return fastapi_testclient.TestClient(app)


@pytest.fixture
def user_client(client, unique_email):
    response = client.post("/api/auth/register", json={"email": unique_email, "password": PASSWORD})
    assert response.status_code == 200, response.text
    return client


@pytest.fixture
def unique_email():
    from uuid import uuid4

    return f"user-{uuid4().hex[:10]}@example.com"


# --- accounts ---------------------------------------------------------------


def test_anonymous_requests_are_rejected(client):
    assert client.get("/api/auth/status").json()["authenticated"] is False
    assert client.get("/api/settings").status_code == 401
    assert client.get("/api/dashboard").status_code == 401


def test_register_login_logout_roundtrip(client, unique_email):
    assert client.post("/api/auth/register", json={"email": unique_email, "password": PASSWORD}).status_code == 200
    assert client.get("/api/auth/status").json()["authenticated"] is True

    assert client.post("/api/auth/logout").status_code == 200
    assert client.get("/api/settings").status_code == 401

    assert client.post("/api/auth/login", json={"email": unique_email, "password": "wrong"}).status_code == 401
    assert client.post("/api/auth/login", json={"email": unique_email, "password": PASSWORD}).status_code == 200


def test_short_password_and_duplicate_email_are_refused(client, unique_email):
    assert client.post("/api/auth/register", json={"email": unique_email, "password": "short"}).status_code == 400
    assert client.post("/api/auth/register", json={"email": unique_email, "password": PASSWORD}).status_code == 200
    assert client.post("/api/auth/register", json={"email": unique_email, "password": PASSWORD}).status_code == 400


def test_password_hashes_are_salted_and_verifiable():
    from webapp.backend import auth

    first = auth.hash_password(PASSWORD)
    second = auth.hash_password(PASSWORD)
    assert first != second  # unique salt per hash
    assert auth.verify_password(PASSWORD, first)
    assert not auth.verify_password("something else", first)


# --- settings ---------------------------------------------------------------


def test_secrets_are_never_returned_to_the_browser(user_client):
    user_client.post("/api/settings", json={"values": {"garmin_email": "a@b.se", "garmin_password": "topsecret"}})
    config = user_client.get("/api/settings").json()["config"]

    assert "garmin_password" not in config
    assert config["garmin_email"] == "a@b.se"
    assert config["secrets_set"]["garmin_password"] is True


def test_blank_secret_keeps_the_stored_value(user_client):
    user_client.post("/api/settings", json={"values": {"anthropic_api_key": "sk-test"}})
    user_client.post("/api/settings", json={"values": {"anthropic_api_key": ""}})

    assert user_client.get("/api/settings").json()["config"]["secrets_set"]["anthropic_api_key"] is True


def test_unknown_settings_keys_are_ignored(user_client):
    user_client.post("/api/settings", json={"values": {"not_a_setting": "x", "user_age": 44}})
    config = user_client.get("/api/settings").json()["config"]

    assert "not_a_setting" not in config
    assert config["user_age"] == 44


# --- per-user isolation -----------------------------------------------------


def test_two_users_do_not_share_data(client, unique_email):
    from uuid import uuid4

    client.post("/api/auth/register", json={"email": unique_email, "password": PASSWORD})
    client.post("/api/settings", json={"values": {"garmin_email": "first@example.com"}})
    client.post("/api/prompts", json={"name": "Mine", "prompt": "Analysera"})

    other = fastapi_testclient.TestClient(app)
    other.post("/api/auth/register", json={"email": f"o-{uuid4().hex[:8]}@example.com", "password": PASSWORD})

    assert other.get("/api/settings").json()["config"]["garmin_email"] == ""
    assert other.get("/api/prompts").json()["prompts"] == []
    assert client.get("/api/prompts").json()["prompts"][0]["name"] == "Mine"


# --- dashboard & charts -----------------------------------------------------


def test_dashboard_returns_all_cards_for_an_empty_database(user_client):
    payload = user_client.get("/api/dashboard?days=30").json()

    assert set(payload["cards"]) == {"fitness", "training_status", "recovery", "weight", "calories"}
    assert payload["cards"]["weight"]["empty"] == "Ingen vikt registrerad"
    assert payload["activities"] == []
    assert payload["sources"] == {"garmin": False, "fitbit": False, "withings": False, "strava": False}


@pytest.mark.parametrize("chart", ["weekly", "trends", "evolab"])
def test_charts_render_as_png(user_client, chart):
    response = user_client.get(f"/api/charts/{chart}.png?days=30")

    assert response.status_code == 200
    assert response.headers["content-type"] == "image/png"
    assert response.content[:8] == b"\x89PNG\r\n\x1a\n"


def test_chart_range_is_validated(user_client):
    assert user_client.get("/api/charts/weekly.png?days=99999").status_code == 422


# --- sync -------------------------------------------------------------------


def test_checkin_without_any_connected_source_is_refused(user_client):
    response = user_client.post("/api/checkin", json={"days": 30, "full": False})

    assert response.status_code == 400
    assert "inte ansluten" in response.json()["detail"].lower()


def test_garmin_connect_requires_credentials(user_client):
    assert user_client.post("/api/garmin/connect").status_code == 400


def test_mfa_requires_six_digits(user_client):
    assert user_client.post("/api/garmin/mfa", json={"code": "123"}).status_code == 400


# --- chat, history and export -----------------------------------------------


def test_chat_requires_a_garmin_connection(user_client):
    response = user_client.post("/api/chat", json={"message": "Hur mår jag?"})

    assert response.status_code == 400
    assert "Garmin" in response.json()["detail"]


def _seed_conversation(email):
    from webapp.backend import auth
    from webapp.backend.workspace import get_workspace

    workspace = get_workspace(auth.get_user_by_email(email)["id"])
    workspace.add_message("You", "Hur ser min sömn ut?", "user")
    workspace.add_message("HealthChat", "**Sömn** var bra.", "assistant")
    return workspace


def test_save_load_rename_and_delete_a_conversation(user_client, unique_email):
    _seed_conversation(unique_email)

    chat_id = user_client.post("/api/chats", json={"name": "Test"}).json()["chat"]["id"]
    assert len(user_client.get("/api/chats").json()["chats"]) == 1
    assert len(user_client.post(f"/api/chats/{chat_id}/load").json()["messages"]) == 2

    renamed = user_client.put(f"/api/chats/{chat_id}", json={"name": "Nytt namn"}).json()
    assert renamed["chats"][0]["name"] == "Nytt namn"
    assert user_client.delete(f"/api/chats/{chat_id}").json()["chats"] == []


def test_saving_an_empty_conversation_is_refused(user_client):
    assert user_client.post("/api/chats", json={"name": "Tom"}).status_code == 400


def test_chat_id_cannot_escape_the_history_directory(user_client):
    assert user_client.get("/api/chats/..%2F..%2Fconfig").status_code in (400, 404)


def test_search_finds_messages_in_the_current_conversation(user_client, unique_email):
    _seed_conversation(unique_email)

    results = user_client.get("/api/search?q=sömn").json()["results"]

    assert results and results[0]["chat"] == "Nuvarande chatt"


@pytest.mark.parametrize("fmt, magic", [("txt", b"GARMIN"), ("pdf", b"%PDF"), ("docx", b"PK")])
def test_export_produces_each_format(user_client, unique_email, fmt, magic):
    _seed_conversation(unique_email)

    response = user_client.post("/api/export", json={"format": fmt})

    assert response.status_code == 200
    assert response.content.startswith(magic)


def test_export_rejects_an_unknown_format(user_client, unique_email):
    _seed_conversation(unique_email)

    assert user_client.post("/api/export", json={"format": "rtf"}).status_code == 400


# --- quick questions & prompts ----------------------------------------------


def test_quick_questions_fall_back_to_the_defaults(user_client):
    assert user_client.get("/api/quick-questions").json()["questions"] == DEFAULT_QUICK_QUESTIONS


def test_quick_questions_are_trimmed_and_capped(user_client):
    saved = user_client.post("/api/quick-questions", json={"questions": [f"q{i}" for i in range(12)] + ["", "  "]})

    assert saved.json()["questions"] == [f"q{i}" for i in range(8)]


def test_prompt_crud(user_client):
    assert user_client.post("/api/prompts", json={"name": "A", "prompt": "p"}).json()["prompts"]
    assert user_client.put("/api/prompts/0", json={"name": "B", "prompt": "p2"}).json()["prompts"][0]["name"] == "B"
    assert user_client.delete("/api/prompts/0").json()["prompts"] == []
    assert user_client.delete("/api/prompts/5").status_code == 404


# --- OAuth ------------------------------------------------------------------


def test_connect_url_requires_a_client_id(user_client):
    assert user_client.get("/api/connect/fitbit/url").status_code == 400


def test_connect_url_is_built_with_the_server_redirect_uri(user_client):
    user_client.post("/api/settings", json={"values": {"strava_client_id": "12345"}})

    payload = user_client.get("/api/connect/strava/url").json()

    assert "strava.com" in payload["url"]
    assert payload["redirect_uri"].endswith("/oauth/strava/callback")


def test_oauth_callback_without_a_code_shows_an_error_page(client):
    response = client.get("/oauth/withings/callback")

    assert response.status_code == 200
    assert "Ingen kod" in response.text


def test_unknown_oauth_provider_is_rejected(user_client):
    assert user_client.get("/api/connect/whoop/url").status_code == 404


# --- frontend ---------------------------------------------------------------


@pytest.mark.parametrize("path", ["/", "/login.html", "/static/app.js", "/static/styles.css"])
def test_frontend_assets_are_served(client, path):
    assert client.get(path).status_code == 200
