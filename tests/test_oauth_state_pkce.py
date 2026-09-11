"""
Unit tests for OAuth CSRF state validation and PKCE S256 implementations across integrations.
"""

from garmin_db import GarminDatabase
from withings_handler import WithingsDataHandler
from strava_handler import StravaHandler
from fitbit_handler import FitbitHandler


def test_withings_oauth_state(tmp_path):
    test_db = GarminDatabase(db_path=tmp_path / "test.db")
    handler = WithingsDataHandler(db=test_db)

    url1 = handler.get_auth_url(client_id="withings_123")
    state1 = handler.current_state

    assert state1 is not None
    assert f"state={state1}" in url1
    assert handler.verify_state(state1) is True
    assert handler.verify_state("invalid_state_token") is False

    url2 = handler.get_auth_url(client_id="withings_123")
    state2 = handler.current_state
    assert state1 != state2


def test_strava_oauth_state(tmp_path):
    test_db = GarminDatabase(db_path=tmp_path / "test.db")
    handler = StravaHandler(db=test_db, token_store_dir=tmp_path)

    url1 = handler.get_auth_url(client_id="strava_123")
    state1 = handler.current_state

    assert state1 is not None
    assert f"state={state1}" in url1
    assert handler.verify_state(state1) is True
    assert handler.verify_state("invalid_state_token") is False

    url2 = handler.get_auth_url(client_id="strava_123")
    state2 = handler.current_state
    assert state1 != state2


def test_fitbit_oauth_state_and_pkce(tmp_path):
    test_db = GarminDatabase(db_path=tmp_path / "test.db")
    handler = FitbitHandler(db=test_db, token_store_dir=tmp_path)

    url = handler.get_auth_url(client_id="fitbit_123")
    state = handler.current_state
    verifier = handler.code_verifier

    assert state is not None
    assert verifier is not None
    assert "code_challenge=" in url
    assert "code_challenge_method=S256" in url
    assert f"state={state}" in url

    assert handler.verify_state(state) is True
    assert handler.verify_state("tampered_state") is False
