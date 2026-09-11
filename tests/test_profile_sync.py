"""
Unit tests for profile_sync module and external profile fetching.
"""

import pytest
from profile_sync import fetch_external_profile_metrics


class DummyDB:
    def get_latest_body_composition(self):
        return {"weight_kg": 82.5}

    def get_daily_summary_history(self, days=30):
        return [
            {"date": "2026-09-10", "resting_hr": 56}
        ]


class DummyGarminHandler:
    authenticated = True
    client = True

    def fetch_user_profile_data(self):
        return {
            "sex": "male",
            "height_cm": 182.0,
            "age": 42.0,
            "weight_kg": 81.5,
            "resting_hr": 54.0,
            "max_hr": 178.0
        }


class DummyFitbitHandler:
    def is_authenticated(self):
        return True

    def fetch_user_profile(self):
        return {
            "weight_kg": 81.0,
            "resting_hr": 53.0
        }


class DummyStravaHandler:
    def is_authenticated(self):
        return True

    def fetch_athlete_profile(self):
        return {
            "sex": "male",
            "weight_kg": 81.2
        }


class DummyWithingsHandler:
    def fetch_profile_data(self):
        return {
            "weight_kg": 80.8
        }


def test_fetch_external_profile_metrics_db_only():
    db = DummyDB()
    res = fetch_external_profile_metrics(db=db)
    metrics = res["metrics"]
    sources = res["sources"]

    assert metrics["weight_kg"] == 82.5
    assert metrics["resting_hr"] == 56
    assert "Databas" in sources


def test_fetch_external_profile_metrics_all_handlers():
    db = DummyDB()
    g_handler = DummyGarminHandler()
    f_handler = DummyFitbitHandler()
    s_handler = DummyStravaHandler()
    w_handler = DummyWithingsHandler()

    res = fetch_external_profile_metrics(
        db=db,
        garmin_handler=g_handler,
        fitbit_handler=f_handler,
        strava_handler=s_handler,
        withings_handler=w_handler
    )
    metrics = res["metrics"]
    sources = res["sources"]

    assert metrics["sex"] == "male"
    assert metrics["height_cm"] == 182.0
    assert metrics["age"] == 42.0
    assert metrics["resting_hr"] == 53.0  # Fitbit was merged last
    assert metrics["weight_kg"] == 80.8   # Withings was merged last
    assert metrics["max_hr"] == 178.0
    assert "Garmin" in sources
    assert "Fitbit" in sources
    assert "Strava" in sources
    assert "Withings" in sources
