"""
Tests for WhoopHandler and Whoop API v2 integration.
"""

import json
from unittest.mock import patch, MagicMock
from pathlib import Path
from datetime import datetime

import pytest
from garmin_db import GarminDatabase
from whoop_handler import WhoopHandler, _uuid_to_int_id, _parse_iso_date, WHOOP_AUTH_URL, WHOOP_TOKEN_URL


@pytest.fixture
def test_db(tmp_path):
    db = GarminDatabase(db_path=tmp_path / "test_whoop.db")
    return db


@pytest.fixture
def handler(test_db, tmp_path):
    token_dir = tmp_path / "whoop_tokens"
    return WhoopHandler(db=test_db, token_store_dir=token_dir)


def test_uuid_to_int_id():
    uuid_str = "ecfc6a15-4661-442f-a9a4-f160dd7afae8"
    int_id = _uuid_to_int_id(uuid_str)
    assert isinstance(int_id, int)
    assert int_id > 0
    # Must fit in signed 64-bit int (MariaDB BIGINT max is 2^63 - 1)
    assert int_id < (2 ** 63)
    # Must be deterministic
    assert _uuid_to_int_id(uuid_str) == int_id


def test_parse_iso_date():
    assert _parse_iso_date("2026-05-24T23:18:00.000Z") == "2026-05-24"
    assert _parse_iso_date("2026-09-19T14:25:44.774+02:00") == "2026-09-19"
    assert len(_parse_iso_date(None)) == 10


def test_whoop_token_save_and_load(handler):
    assert handler.is_authenticated() is False
    tokens = {
        "access_token": "whoop_test_access",
        "refresh_token": "whoop_test_refresh",
        "expires_in": 3600,
        "client_id": "test_client",
        "client_secret": "test_secret",
    }
    handler.save_tokens(tokens)
    assert handler.is_authenticated() is True
    assert handler.access_token == "whoop_test_access"
    assert handler.refresh_token == "whoop_test_refresh"

    # Reload from disk
    new_handler = WhoopHandler(db=handler.db, token_store_dir=handler.token_store_dir)
    assert new_handler.is_authenticated() is True
    assert new_handler.access_token == "whoop_test_access"
    assert new_handler.refresh_token == "whoop_test_refresh"


def test_get_auth_url_and_verify_state(handler):
    redirect_uri = "https://example.com/api/datasources/whoop/callback"
    auth_url = handler.get_auth_url(client_id="client_123", redirect_uri=redirect_uri)
    assert WHOOP_AUTH_URL in auth_url
    assert "client_id=client_123" in auth_url
    assert "read%3Arecovery" in auth_url or "read:recovery" in auth_url
    assert "read%3Asleep" in auth_url or "read:sleep" in auth_url
    assert "offline" in auth_url

    assert handler.verify_state(handler.current_state) is True
    assert handler.verify_state("fake_state") is False


def test_exchange_code_for_token_success(handler):
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "access_token": "new_whoop_access",
        "refresh_token": "new_whoop_refresh",
        "expires_in": 3600,
    }

    with patch("requests.post", return_value=mock_resp) as mock_post:
        tokens = handler.exchange_code_for_token(
            code="auth_code_123",
            client_id="cid",
            client_secret="csec",
            redirect_uri="https://example.com/cb",
        )
        assert tokens["access_token"] == "new_whoop_access"
        assert handler.is_authenticated() is True
        mock_post.assert_called_once()


def test_refresh_access_token_success(handler):
    handler.save_tokens({
        "access_token": "old_token",
        "refresh_token": "valid_refresh",
        "client_id": "cid",
        "client_secret": "csec",
    })

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "access_token": "refreshed_access",
        "refresh_token": "refreshed_refresh",
        "expires_in": 3600,
    }

    with patch("requests.post", return_value=mock_resp):
        assert handler.refresh_access_token() is True
        assert handler.access_token == "refreshed_access"


def test_fetch_user_profile(handler):
    handler.access_token = "valid_token"
    handler._authenticated = True

    def fake_get(url, **kwargs):
        resp = MagicMock()
        resp.status_code = 200
        if "profile/basic" in url:
            resp.json.return_value = {"first_name": "Anna", "last_name": "Andersson", "email": "anna@example.se"}
        elif "measurement/body" in url:
            resp.json.return_value = {"height_meter": 1.78, "weight_kilogram": 72.4, "max_heart_rate": 185}
        return resp

    with patch("requests.get", side_effect=fake_get):
        profile = handler.fetch_user_profile()
        assert profile["name"] == "Anna Andersson"
        assert profile["email"] == "anna@example.se"
        assert profile["height_cm"] == 178.0
        assert profile["weight_kg"] == 72.4
        assert profile["max_hr"] == 185


def test_sync_whoop_history_all_domains(handler, test_db):
    handler.access_token = "valid_token"
    handler._authenticated = True

    today = datetime.now().strftime("%Y-%m-%d")

    def fake_get(url, **kwargs):
        resp = MagicMock()
        resp.status_code = 200
        if "measurement/body" in url:
            resp.json.return_value = {"height_meter": 1.82, "weight_kilogram": 78.5}
        elif "activity/sleep" in url:
            resp.json.return_value = {
                "records": [
                    {
                        "id": "11111111-1111-1111-1111-111111111111",
                        "start": f"{today}T00:00:00.000Z",
                        "end": f"{today}T07:30:00.000Z",
                        "score": {
                            "sleep_performance_percentage": 89,
                            "stage_summary": {
                                "total_in_bed_time_milli": 27000000,
                                "rem_sleep_duration_milli": 7200000,
                                "slow_wave_sleep_duration_milli": 5400000,
                                "light_sleep_duration_milli": 12600000,
                            },
                        },
                    }
                ],
                "next_token": None,
            }
        elif "recovery" in url:
            resp.json.return_value = {
                "records": [
                    {
                        "cycle_id": 9999,
                        "created_at": f"{today}T07:30:00.000Z",
                        "score": {
                            "recovery_score": 82,
                            "resting_heart_rate": 51,
                            "hrv_rmssd_milli": 55.4,
                        },
                    }
                ],
                "next_token": None,
            }
        elif "cycle" in url:
            resp.json.return_value = {
                "records": [
                    {
                        "id": 9999,
                        "start": f"{today}T00:00:00.000Z",
                        "score": {
                            "strain": 14.2,
                            "kilojoule": 8500.0,
                            "average_heart_rate": 72,
                        },
                    }
                ],
                "next_token": None,
            }
        elif "activity/workout" in url:
            resp.json.return_value = {
                "records": [
                    {
                        "id": "22222222-2222-2222-2222-222222222222",
                        "start": f"{today}T10:00:00.000Z",
                        "end": f"{today}T11:00:00.000Z",
                        "sport_name": "running",
                        "score": {
                            "strain": 15.1,
                            "kilojoule": 2400.0,
                            "average_heart_rate": 152,
                            "max_heart_rate": 174,
                            "distance_meter": 10200.0,
                        },
                    }
                ],
                "next_token": None,
            }
        else:
            resp.json.return_value = {}
        return resp

    import threading
    done = threading.Event()
    outcome = {}

    def on_complete(count, err):
        outcome["count"] = count
        outcome["err"] = err
        done.set()

    with patch("requests.get", side_effect=fake_get):
        handler.sync_whoop_history(days=7, on_complete=on_complete)
        assert done.wait(timeout=10)

    assert outcome.get("err") is None
    assert outcome.get("count", 0) >= 5

    # Check sleep stored in DB
    sleep_rows = test_db.get_sleep_history(days=7)
    assert len(sleep_rows) >= 1
    assert sleep_rows[0]["sleep_score"] == 89

    # Check HRV stored in DB
    hrv_rows = test_db.get_hrv_history(days=7)
    assert len(hrv_rows) >= 1
    assert hrv_rows[0]["last_night_avg"] == 55.4

    # Check Body Battery (recovery score) stored in DB
    bb_rows = test_db.get_body_battery_history(days=7)
    assert len(bb_rows) >= 1
    assert bb_rows[0]["charged"] == 82

    # Check daily summary (calories from cycle)
    summary = test_db.get_daily_summary(today)
    assert summary is not None
    assert summary.get("total_calories") == int(round(8500.0 * 0.239006))

    # Check workout stored in DB
    activities = test_db.get_activities_history(days=7)
    assert len(activities) >= 1
    assert activities[0]["source"] == "Whoop"
    assert activities[0]["distance_km"] == 10.2
    assert activities[0]["avg_hr"] == 152
