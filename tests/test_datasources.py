"""
Tests for the Datakällor feature: per-user encrypted datasource storage
(datasource_store) and the /api/datasources endpoints in server.py.
"""

from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient

import auth
import server
import datasource_store
from garmin_db import GarminDatabase

TEST_DEK = bytes(bytearray(range(32)))
TEST_USER_ID = 4242


# --- PROVIDER CATALOGUE -----------------------------------------------------

def test_provider_catalogue_covers_all_sources():
    assert set(datasource_store.PROVIDERS) == {"strava", "garmin", "withings", "fitbit", "whoop"}
    assert datasource_store.PROVIDER_ORDER == ["strava", "garmin", "withings", "fitbit", "whoop"]


def test_every_provider_has_required_metadata():
    for provider, meta in datasource_store.PROVIDERS.items():
        for key in ("name", "icon", "color", "auth_kind", "description",
                    "portal_url", "portal_label", "steps", "sync_days", "sync_label"):
            assert meta.get(key), f"{provider} saknar metadata-nyckeln {key}"
        assert meta["auth_kind"] in ("oauth", "credentials")
        assert meta["portal_url"].startswith("https://")
        assert len(meta["steps"]) >= 3


def test_garmin_uses_credentials_and_the_rest_use_oauth():
    assert datasource_store.PROVIDERS["garmin"]["auth_kind"] == "credentials"
    for provider in ("strava", "withings", "fitbit", "whoop"):
        assert datasource_store.PROVIDERS[provider]["auth_kind"] == "oauth"


def test_unknown_provider_is_rejected():
    assert datasource_store.is_valid_provider("polar") is False
    with pytest.raises(ValueError):
        datasource_store.load_record(None, TEST_USER_ID, TEST_DEK, "polar")


# --- ENCRYPTED STORAGE ------------------------------------------------------

@pytest.fixture
def ds_conn(tmp_path):
    db = GarminDatabase(db_path=tmp_path / "datasources.db")
    conn = db.get_connection()
    datasource_store.ensure_table(conn)
    yield conn
    conn.close()


def test_missing_record_returns_empty_defaults(ds_conn):
    record = datasource_store.load_record(ds_conn, TEST_USER_ID, TEST_DEK, "strava")
    assert record["payload"] == {}
    assert record["connected"] is False
    assert record["exists"] is False
    assert record["last_sync_count"] == 0


def test_save_and_load_round_trip(ds_conn):
    payload = {"client_id": "12345", "client_secret": "shhh", "access_token": "at-1", "refresh_token": "rt-1"}
    datasource_store.save_record(ds_conn, TEST_USER_ID, TEST_DEK, "strava", payload, connected=True)

    record = datasource_store.load_record(ds_conn, TEST_USER_ID, TEST_DEK, "strava")
    assert record["payload"] == payload
    assert record["connected"] is True
    assert record["exists"] is True


def test_payload_is_encrypted_at_rest(ds_conn):
    datasource_store.save_record(
        ds_conn, TEST_USER_ID, TEST_DEK, "withings",
        {"client_id": "wid", "client_secret": "top-secret-value"}
    )
    cur = ds_conn.cursor()
    cur.execute(f"SELECT encrypted_payload FROM {datasource_store.TABLE_NAME} WHERE user_id = ?", (TEST_USER_ID,))
    stored = bytes(cur.fetchone()[0])
    cur.close()
    assert b"top-secret-value" not in stored
    assert b"client_secret" not in stored


def test_save_preserves_metadata_when_not_supplied(ds_conn):
    datasource_store.save_record(
        ds_conn, TEST_USER_ID, TEST_DEK, "fitbit", {"client_id": "fid", "client_secret": "fsec"},
        connected=True, last_sync_at="2026-09-01 10:00:00", last_sync_count=17
    )
    datasource_store.save_record(
        ds_conn, TEST_USER_ID, TEST_DEK, "fitbit", {"client_id": "fid2", "client_secret": "fsec"}
    )
    record = datasource_store.load_record(ds_conn, TEST_USER_ID, TEST_DEK, "fitbit")
    assert record["payload"]["client_id"] == "fid2"
    assert record["connected"] is True
    assert record["last_sync_at"] == "2026-09-01 10:00:00"
    assert record["last_sync_count"] == 17


def test_records_are_isolated_per_user(ds_conn):
    datasource_store.save_record(ds_conn, 1, TEST_DEK, "strava", {"client_id": "user-one"})
    datasource_store.save_record(ds_conn, 2, TEST_DEK, "strava", {"client_id": "user-two"})
    assert datasource_store.load_record(ds_conn, 1, TEST_DEK, "strava")["payload"]["client_id"] == "user-one"
    assert datasource_store.load_record(ds_conn, 2, TEST_DEK, "strava")["payload"]["client_id"] == "user-two"


def test_delete_record_removes_credentials(ds_conn):
    datasource_store.save_record(ds_conn, TEST_USER_ID, TEST_DEK, "strava", {"client_id": "x"}, connected=True)
    datasource_store.delete_record(ds_conn, TEST_USER_ID, "strava")
    record = datasource_store.load_record(ds_conn, TEST_USER_ID, TEST_DEK, "strava")
    assert record["exists"] is False
    assert record["connected"] is False


def test_wrong_dek_cannot_decrypt_payload(ds_conn):
    datasource_store.save_record(ds_conn, TEST_USER_ID, TEST_DEK, "strava", {"client_id": "secret-id"})
    other_dek = bytes(bytearray(reversed(range(32))))
    record = datasource_store.load_record(ds_conn, TEST_USER_ID, other_dek, "strava")
    assert record["payload"] == {}


# --- PUBLIC STATUS ----------------------------------------------------------

def test_public_status_never_exposes_secrets():
    record = {
        "payload": {
            "client_id": "cid", "client_secret": "csecret",
            "access_token": "at", "refresh_token": "rt",
            "code_verifier": "cv", "oauth_state": "state", "password": "pw",
        },
        "connected": True, "last_sync_at": "2026-09-01 08:00:00", "last_sync_count": 5,
    }
    status_obj = datasource_store.public_status("strava", record, "https://example.se/cb")
    serialized = repr(status_obj)
    for secret in ("csecret", "at", "rt", "cv", "state", "pw"):
        assert f"'{secret}'" not in serialized
    for field in datasource_store.SECRET_FIELDS:
        assert field not in status_obj
    assert status_obj["client_id"] == "cid"
    assert status_obj["secret_set"] is True
    assert status_obj["has_credentials"] is True
    assert status_obj["callback_url"] == "https://example.se/cb"


def test_public_status_requires_email_and_password_for_garmin():
    partial = {"payload": {"email": "a@b.se"}, "connected": False, "last_sync_at": None, "last_sync_count": 0}
    assert datasource_store.public_status("garmin", partial)["has_credentials"] is False
    full = {"payload": {"email": "a@b.se", "password": "pw"}, "connected": False,
            "last_sync_at": None, "last_sync_count": 0}
    assert datasource_store.public_status("garmin", full)["has_credentials"] is True


def test_has_tokens_per_provider():
    assert datasource_store.has_tokens("strava", {"access_token": "at"}) is True
    assert datasource_store.has_tokens("strava", {"client_id": "cid"}) is False
    assert datasource_store.has_tokens("withings", {"refresh_token": "rt"}) is True
    assert datasource_store.has_tokens("garmin", {"oauth2_token": {"a": 1}}) is True
    assert datasource_store.has_tokens("garmin", {"email": "a@b.se", "password": "pw"}) is True
    assert datasource_store.has_tokens("garmin", {"email": "a@b.se"}) is False


# --- API ENDPOINTS ----------------------------------------------------------

@pytest.fixture
def ds_api(tmp_path, monkeypatch):
    """TestClient with an authenticated session backed by a throwaway SQLite db."""
    session_id = "datasource-test-session"
    session = auth.UserSession(
        user_id=TEST_USER_ID,
        email="datakalla@example.com",
        dek=bytearray(TEST_DEK),
        encrypted_profile={"sex": "male", "age": 40},
    )
    server._active_sessions[session_id] = session
    server._session_expirations[session_id] = datetime.now() + timedelta(hours=1)

    db = GarminDatabase(db_path=tmp_path / "api_datasources.db")
    seed_conn = db.get_connection()
    datasource_store.ensure_table(seed_conn)
    seed_conn.close()

    monkeypatch.setattr(server, "bind_user_db", lambda s, require_mariadb=True: db)
    monkeypatch.setattr(server, "get_db_conn", lambda d: db.get_connection())
    monkeypatch.setattr(server, "build_worker_db", lambda user_id, dek: db)

    client = TestClient(
        server.app,
        base_url="https://testserver",
        cookies={"healthchat_session": session_id},
    )
    try:
        yield client, db
    finally:
        server._active_sessions.pop(session_id, None)
        server._session_expirations.pop(session_id, None)
        server._sync_jobs.clear()


def test_list_datasources_requires_login():
    anon = TestClient(server.app, base_url="https://testserver")
    assert anon.get("/api/datasources").status_code == 401


def test_list_datasources_returns_all_providers(ds_api):
    client, _db = ds_api
    res = client.get("/api/datasources")
    assert res.status_code == 200, res.text
    providers = res.json()["providers"]
    assert [p["provider"] for p in providers] == datasource_store.PROVIDER_ORDER
    for p in providers:
        assert p["connected"] is False
        assert p["has_credentials"] is False
        for field in datasource_store.SECRET_FIELDS:
            assert field not in p


def test_callback_url_points_at_the_provider_endpoint(ds_api):
    client, _db = ds_api
    providers = client.get("/api/datasources").json()["providers"]
    strava = next(p for p in providers if p["provider"] == "strava")
    assert strava["callback_url"].endswith("/api/datasources/strava/callback")


def test_unknown_provider_returns_404(ds_api):
    client, _db = ds_api
    res = client.post("/api/datasources/polar/credentials", json={"client_id": "x", "client_secret": "y"})
    assert res.status_code == 404


def test_save_credentials_and_status_reflects_them(ds_api):
    client, _db = ds_api
    res = client.post(
        "/api/datasources/strava/credentials",
        json={"client_id": "123456", "client_secret": "super-secret"},
    )
    assert res.status_code == 200, res.text
    status_obj = res.json()["provider_status"]
    assert status_obj["client_id"] == "123456"
    assert status_obj["secret_set"] is True
    assert status_obj["has_credentials"] is True
    assert status_obj["connected"] is False
    assert "super-secret" not in res.text


def test_save_credentials_requires_client_secret(ds_api):
    client, _db = ds_api
    res = client.post("/api/datasources/fitbit/credentials", json={"client_id": "abc"})
    assert res.status_code == 400
    assert "Client Secret" in res.json()["detail"]


def test_credentials_endpoint_rejects_garmin(ds_api):
    client, _db = ds_api
    res = client.post("/api/datasources/garmin/credentials", json={"client_id": "a", "client_secret": "b"})
    assert res.status_code == 400


def test_authorize_requires_saved_credentials(ds_api):
    client, _db = ds_api
    res = client.post("/api/datasources/withings/authorize")
    assert res.status_code == 400
    assert "Client ID" in res.json()["detail"]


def test_authorize_builds_state_backed_auth_url(ds_api):
    client, db = ds_api
    client.post("/api/datasources/strava/credentials", json={"client_id": "123456", "client_secret": "sec"})

    res = client.post("/api/datasources/strava/authorize")
    assert res.status_code == 200, res.text
    data = res.json()
    assert data["auth_url"].startswith("https://www.strava.com/oauth/authorize")
    assert "client_id=123456" in data["auth_url"]
    assert "state=" in data["auth_url"]
    assert data["redirect_uri"].endswith("/api/datasources/strava/callback")

    conn = db.get_connection()
    try:
        record = datasource_store.load_record(conn, TEST_USER_ID, TEST_DEK, "strava")
    finally:
        conn.close()
    assert record["payload"]["oauth_state"] in data["auth_url"]
    assert record["payload"]["redirect_uri"] == data["redirect_uri"]


def test_fitbit_authorize_stores_pkce_verifier(ds_api):
    client, db = ds_api
    client.post("/api/datasources/fitbit/credentials", json={"client_id": "fid", "client_secret": "fsec"})
    res = client.post("/api/datasources/fitbit/authorize")
    assert res.status_code == 200, res.text
    assert "code_challenge_method=S256" in res.json()["auth_url"]

    conn = db.get_connection()
    try:
        payload = datasource_store.load_record(conn, TEST_USER_ID, TEST_DEK, "fitbit")["payload"]
    finally:
        conn.close()
    assert payload.get("code_verifier")


def test_callback_rejects_mismatched_state(ds_api, monkeypatch):
    client, _db = ds_api
    client.post("/api/datasources/strava/credentials", json={"client_id": "123456", "client_secret": "sec"})
    client.post("/api/datasources/strava/authorize")

    res = client.get("/api/datasources/strava/callback", params={"code": "abc", "state": "forged"})
    assert res.status_code == 400
    assert "state" in res.text


def test_callback_without_session_is_refused():
    anon = TestClient(server.app, base_url="https://testserver")
    res = anon.get("/api/datasources/strava/callback", params={"code": "abc", "state": "x"})
    assert res.status_code == 400
    assert "session" in res.text.lower()


def test_callback_stores_tokens_and_marks_connected(ds_api, monkeypatch):
    client, db = ds_api
    client.post("/api/datasources/strava/credentials", json={"client_id": "123456", "client_secret": "sec"})
    client.post("/api/datasources/strava/authorize")

    conn = db.get_connection()
    try:
        state = datasource_store.load_record(conn, TEST_USER_ID, TEST_DEK, "strava")["payload"]["oauth_state"]
    finally:
        conn.close()

    class FakeStrava:
        def __init__(self):
            self.access_token = None
            self.refresh_token = None
            self.expires_at = None

        def exchange_code_for_token(self, code, client_id, client_secret, redirect_uri=""):
            assert code == "auth-code-1"
            assert client_id == "123456"
            assert client_secret == "sec"
            assert redirect_uri.endswith("/api/datasources/strava/callback")
            self.access_token = "new-access"
            self.refresh_token = "new-refresh"
            self.expires_at = 1893456000
            return {"access_token": self.access_token}

    monkeypatch.setattr(datasource_store, "build_handler", lambda *a, **kw: FakeStrava())

    res = client.get("/api/datasources/strava/callback", params={"code": "auth-code-1", "state": state})
    assert res.status_code == 200, res.text
    assert "ansluten" in res.text.lower()

    conn = db.get_connection()
    try:
        record = datasource_store.load_record(conn, TEST_USER_ID, TEST_DEK, "strava")
    finally:
        conn.close()
    assert record["connected"] is True
    assert record["payload"]["access_token"] == "new-access"
    assert record["payload"]["refresh_token"] == "new-refresh"
    # Single-use CSRF/PKCE material must be cleared after the exchange.
    assert "oauth_state" not in record["payload"]


def test_sync_requires_a_connected_source(ds_api):
    client, _db = ds_api
    res = client.post("/api/datasources/withings/sync", json={})
    assert res.status_code == 400
    assert "inte anslutet" in res.json()["detail"]


def test_sync_runs_and_records_the_result(ds_api, monkeypatch):
    client, db = ds_api
    conn = db.get_connection()
    try:
        datasource_store.save_record(
            conn, TEST_USER_ID, TEST_DEK, "withings",
            {"client_id": "wid", "client_secret": "wsec", "refresh_token": "rt"},
            connected=True,
        )
    finally:
        conn.close()

    def fake_sync(provider, database, payload, days=None, force_full=False, timeout=900.0, on_progress=None):
        if on_progress:
            on_progress("Hämtar mätvärden...")
        return {"success": True, "count": 12, "message": "12 mätvärden sparade.",
                "tokens": {"access_token": "fresh-at", "refresh_token": "fresh-rt"}}

    monkeypatch.setattr(datasource_store, "sync_provider", fake_sync)

    res = client.post("/api/datasources/withings/sync", json={})
    assert res.status_code == 200, res.text
    assert res.json()["status"] == "running"

    # The worker thread is short-lived here; poll until it reports a terminal state.
    for _ in range(50):
        status_res = client.get("/api/datasources/withings/sync_status")
        assert status_res.status_code == 200
        if status_res.json()["status"] != "running":
            break
    payload_status = status_res.json()
    assert payload_status["status"] == "done", payload_status
    assert payload_status["count"] == 12

    conn = db.get_connection()
    try:
        record = datasource_store.load_record(conn, TEST_USER_ID, TEST_DEK, "withings")
    finally:
        conn.close()
    assert record["payload"]["access_token"] == "fresh-at"
    assert record["last_sync_count"] == 12
    assert record["last_sync_at"]


def test_sync_status_is_idle_before_any_sync(ds_api):
    client, _db = ds_api
    res = client.get("/api/datasources/fitbit/sync_status")
    assert res.status_code == 200
    assert res.json()["status"] == "idle"


def test_sync_all_and_status(ds_api):
    client, db = ds_api
    # Check status before sync_all
    st_res = client.get("/api/datasources/sync_all_status")
    assert st_res.status_code == 200
    data = st_res.json()
    assert "running" in data
    assert "jobs" in data

    # Trigger sync_all when no providers are connected
    sync_res = client.post("/api/datasources/sync_all")
    assert sync_res.status_code == 200
    res_data = sync_res.json()
    assert res_data["status"] in ("idle", "started")
    assert "count" in res_data





def test_disconnect_clears_stored_credentials(ds_api):
    client, db = ds_api
    conn = db.get_connection()
    try:
        datasource_store.save_record(
            conn, TEST_USER_ID, TEST_DEK, "strava",
            {"client_id": "cid", "client_secret": "sec", "access_token": "at"},
            connected=True,
        )
    finally:
        conn.close()

    res = client.post("/api/datasources/strava/disconnect")
    assert res.status_code == 200, res.text
    assert res.json()["provider_status"]["connected"] is False

    conn = db.get_connection()
    try:
        record = datasource_store.load_record(conn, TEST_USER_ID, TEST_DEK, "strava")
    finally:
        conn.close()
    assert record["exists"] is False


def test_garmin_connect_requires_email_and_password(ds_api):
    client, _db = ds_api
    res = client.post("/api/datasources/garmin/connect", json={"email": "", "password": ""})
    assert res.status_code == 400


def test_garmin_connect_signals_mfa_and_then_succeeds(ds_api, monkeypatch):
    client, db = ds_api

    class FakeGarmin:
        def __init__(self):
            self.calls = 0

        def authenticate(self):
            return {"mfa_required": True}

        def submit_mfa(self, code):
            assert code == "123456"
            return {"success": True}

    fake = FakeGarmin()
    monkeypatch.setattr(datasource_store, "build_handler", lambda *a, **kw: fake)
    monkeypatch.setattr(
        datasource_store, "collect_tokens",
        lambda provider, handler, token_dir=None: {"oauth2_token": {"access_token": "garmin-at"}},
    )

    first = client.post(
        "/api/datasources/garmin/connect",
        json={"email": "run@example.se", "password": "hemligt", "save_credentials": True},
    )
    assert first.status_code == 200, first.text
    assert first.json()["status"] == "mfa_required"

    second = client.post("/api/datasources/garmin/connect", json={"mfa_code": "123456"})
    assert second.status_code == 200, second.text
    assert second.json()["status"] == "connected"
    assert second.json()["provider_status"]["email"] == "run@example.se"
    assert "hemligt" not in second.text

    conn = db.get_connection()
    try:
        record = datasource_store.load_record(conn, TEST_USER_ID, TEST_DEK, "garmin")
    finally:
        conn.close()
    assert record["connected"] is True
    assert record["payload"]["oauth2_token"] == {"access_token": "garmin-at"}
    assert record["payload"]["password"] == "hemligt"


def test_unexpected_failure_returns_a_readable_json_error(ds_api, monkeypatch):
    """A crash must not become a bare 500 the frontend cannot parse into a message."""
    client, _db = ds_api

    def boom(*args, **kwargs):
        raise OSError("hemlig intern detalj fran undantaget")

    monkeypatch.setattr(datasource_store, "build_handler", boom)

    res = client.post(
        "/api/datasources/garmin/connect",
        json={"email": "run@example.se", "password": "hemligt"},
    )
    assert res.status_code == 500
    assert "application/json" in res.headers["content-type"]
    detail = res.json()["detail"]
    assert "Garmin-anslutningen" in detail
    assert "OSError" in detail
    assert "Felkod" in detail
    # The exception message itself stays server side - it can carry connection
    # strings or URLs with tokens.
    assert "hemlig intern detalj" not in res.text


def test_garmin_mfa_without_pending_login_is_refused(ds_api):
    client, _db = ds_api
    server._pending_garmin.pop(TEST_USER_ID, None)
    res = client.post("/api/datasources/garmin/connect", json={"mfa_code": "999999"})
    assert res.status_code == 400
    assert "pågående" in res.json()["detail"]


# --- FRONTEND WIRING --------------------------------------------------------

def test_frontend_exposes_the_datakallor_tab():
    from pathlib import Path
    root = Path(__file__).resolve().parent.parent
    index_html = (root / "static" / "index.html").read_text(encoding="utf-8")
    app_js = (root / "static" / "app.js").read_text(encoding="utf-8")

    assert "tab-btn-datasources" in index_html
    assert "Datakällor" in index_html
    assert 'id="tab-datasources"' in index_html
    assert 'id="ds-cards"' in index_html
    # The tab sits next to Profil & Konto in the navbar.
    assert index_html.index("tab-btn-profile") < index_html.index("tab-btn-datasources")

    assert "async function loadDatasources()" in app_js
    assert "handleAuthorizeDatasource" in app_js
    assert "handleGarminConnect" in app_js
    assert "handleDisconnectDatasource" in app_js
    assert "handleSyncDatasource" in app_js


def test_account_deletion_also_drops_datasource_rows():
    from pathlib import Path
    auth_src = (Path(__file__).resolve().parent.parent / "auth.py").read_text(encoding="utf-8")
    assert "DELETE FROM user_datasources WHERE user_id" in auth_src
