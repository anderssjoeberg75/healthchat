"""
Unit tests for Omgång 6 (B-5, B-6, B-7, S-16).
"""

import os
import time
import pytest
import threading
import sqlite3
from unittest.mock import MagicMock, patch

from garmin_handler import GarminDataHandler
from withings_handler import WithingsDataHandler
from strava_handler import StravaHandler
from fitbit_handler import FitbitHandler
import auth


def test_b5_garmin_mfa_wait_succeeds_when_prompt_delayed(tmp_path):
    """B-5: Verify that delayed MFA prompt (e.g., takes 2s to arrive) is properly caught."""
    handler = GarminDataHandler(email="user@test.com", password="pwd", token_store_path=str(tmp_path / "tokens"))

    # Mock garth to simulate MFA prompt being called after 0.5 seconds
    def mock_login(email, password, prompt_mfa=None):
        time.sleep(0.5)
        if prompt_mfa:
            code = prompt_mfa()
            if code == "123456":
                return True
        raise RuntimeError("MFA failed")

    with patch("garmin_handler.garth") as mock_garth:
        mock_garth.login.side_effect = mock_login
        res = handler.authenticate()
        assert res == {"mfa_required": True}
        assert handler.client_state is not None
        assert "mfa_event" in handler.client_state


def test_b6_withings_operator_precedence_preserves_error():
    """B-6: Verify operator precedence correctly handles status_code None and status_code 0."""
    handler = WithingsDataHandler(client_id="id", client_secret="secret")

    # Case 1: err_detail exists, status_code is None
    with patch.object(handler, "refresh_access_token", return_value={"success": False}):
        with patch("requests.post") as mock_post:
            mock_post.return_value.json.return_value = {"error": "invalid_grant", "status": None}
            with pytest.raises(ValueError) as excinfo:
                handler.exchange_code_for_token("bad_code", "id", "secret")
            assert "invalid_grant" in str(excinfo.value)

    # Case 2: status_code is 503, no err_detail
    with patch.object(handler, "refresh_access_token", return_value={"success": False}):
        with patch("requests.post") as mock_post:
            mock_post.return_value.json.return_value = {"error": None, "status": 503}
            with pytest.raises(ValueError) as excinfo:
                handler.exchange_code_for_token("bad_code", "id", "secret")
            assert "Withings API-status 503" in str(excinfo.value)


def test_b7_strava_and_fitbit_token_refresh_failure_raises_clear_error(tmp_path):
    """B-7: Verify that failed token refresh raises explicit RuntimeError."""
    mock_db = MagicMock()
    strava = StravaHandler(db=mock_db, token_store_dir=tmp_path)
    strava.access_token = "old_token"
    strava.expires_at = time.time() - 100  # Expired

    with patch.object(strava, "refresh_access_token", return_value=False):
        with pytest.raises(RuntimeError) as excinfo:
            strava._get_headers()
        assert "Strava-anslutningen har gått ut" in str(excinfo.value)

    fitbit = FitbitHandler(db=mock_db, token_store_dir=tmp_path)
    fitbit.access_token = "old_token"
    fitbit.expires_at = time.time() - 100  # Expired

    with patch.object(fitbit, "refresh_access_token", return_value=False):
        with pytest.raises(RuntimeError) as excinfo:
            fitbit._get_headers()
        assert "Fitbit-anslutningen har gått ut" in str(excinfo.value)


def test_s16_delete_user_account_clears_keyring(monkeypatch):
    """S-16: Verify that delete_user_account retrieves email and calls clear_remembered_session(email)."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("CREATE TABLE users (id INTEGER PRIMARY KEY, email TEXT)")
    conn.execute("CREATE TABLE user_sessions (session_id TEXT, user_id INTEGER)")
    conn.execute("INSERT INTO users (id, email) VALUES (1, 'delete_me@example.com')")
    conn.execute("INSERT INTO user_sessions (session_id, user_id) VALUES ('sid-1', 1)")
    conn.commit()

    cleared_emails = []

    def mock_clear_remembered_session(email=None):
        cleared_emails.append(email)

    monkeypatch.setattr(auth, "clear_remembered_session", mock_clear_remembered_session)

    auth.delete_user_account(conn, 1)

    assert "delete_me@example.com" in cleared_emails
    cursor = conn.execute("SELECT COUNT(*) FROM users WHERE id = 1")
    assert cursor.fetchone()[0] == 0
    s_cursor = conn.execute("SELECT COUNT(*) FROM user_sessions WHERE user_id = 1")
    assert s_cursor.fetchone()[0] == 0
