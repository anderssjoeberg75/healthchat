"""Tests for garmin_handler formatting edge cases."""

from unittest.mock import MagicMock
import pytest
from garmin_handler import GarminDataHandler


def test_get_formatted_health_summary_with_none_sleep_and_stress_values():
    handler = GarminDataHandler.__new__(GarminDataHandler)
    handler._ensure_authenticated = MagicMock()
    handler._ensure_display_name = MagicMock()
    handler.client = MagicMock(display_name="testuser")
    handler.get_user_summary = MagicMock(return_value=None)
    handler.get_floors_data = MagicMock(return_value=None)
    handler.get_activities = MagicMock(return_value=[])
    handler.get_sleep_data = MagicMock(return_value={
        "dailySleepDTO": {
            "calendarDate": "2026-08-19",
            "sleepTimeSeconds": None,
            "deepSleepSeconds": None,
            "lightSleepSeconds": None,
            "remSleepSeconds": None,
            "awakeSleepSeconds": None,
        }
    })
    handler.get_heart_rate_data = MagicMock(return_value=None)
    handler.get_body_battery = MagicMock(return_value=None)
    handler.get_stress_data = MagicMock(return_value={
        "average": 25,
        "date": "2026-08-19",
        "low_duration": None,
        "high_duration": None,
    })
    handler.get_respiration_data = MagicMock(return_value=None)
    handler.get_hydration_data = MagicMock(return_value={"valueInML": None})
    handler.get_calories_data = MagicMock(return_value=None)
    handler.get_nutrition_summary = MagicMock(return_value=None)
    handler.get_food_log = MagicMock(return_value=None)

    summary = handler.format_data_for_context(data_type="comprehensive")
    assert "Deep Sleep: 0.0 hours" in summary
    assert "Low Stress Duration: 0 min" in summary
    assert "Water Intake: 0 ml" in summary


def test_extract_body_composition():
    # Test format with totalAverage and weight in grams
    data = {
        "totalAverage": {
            "weight": 78500,
            "bmi": 24.2,
            "bodyFat": 18.5,
            "bodyWater": 56.0,
            "boneMass": 3400,
            "muscleMass": 35000
        }
    }
    res = GarminDataHandler.extract_body_composition(data, "2026-08-25")
    assert res["date"] == "2026-08-25"
    assert res["weight_kg"] == 78.5
    assert res["bmi"] == 24.2
    assert res["fat_ratio_pct"] == 18.5
    assert res["muscle_mass_kg"] == 35.0
    assert res["bone_mass_kg"] == 3.4
    assert res["water_pct"] == 56.0

    # Test dateWeightList format override
    data_list = {
        "totalAverage": {"weight": 78500},
        "dateWeightList": [
            {
                "calendarDate": "2026-08-25",
                "weight": 77000,
                "bmi": 23.8,
                "bodyFat": 17.9,
                "bodyWater": 57.0,
                "boneMass": 3300,
                "muscleMass": 34500
            }
        ]
    }
    res_list = GarminDataHandler.extract_body_composition(data_list, "2026-08-25")
    assert res_list["weight_kg"] == 77.0
    assert res_list["bmi"] == 23.8


def test_sync_garmin_history_incremental_and_body_composition(db):
    handler = GarminDataHandler.__new__(GarminDataHandler)
    handler._authenticated = True
    handler.db = db
    handler.client = MagicMock()
    handler.get_activities = MagicMock(return_value=[])

    handler.client.get_sleep_data = MagicMock(return_value={})
    handler.client.get_body_battery = MagicMock(return_value={})
    handler.client.get_stress_data = MagicMock(return_value={})
    handler.client.get_hrv_data = MagicMock(return_value={})
    handler.client.get_body_composition = MagicMock(return_value={
        "totalAverage": {"weight": 80000, "bodyFat": 19.0}
    })

    # Set last sync to yesterday so diff_days is 3 days
    from datetime import datetime, timedelta
    yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
    db.set_metadata("last_garmin_sync", yesterday)

    done_event = MagicMock()
    handler.sync_garmin_history(days=30, force_full=False, on_complete=done_event)

    import time
    time.sleep(0.5)

    # get_sleep_data should have been called 3 times (incremental: yesterday, today, +1 overlap) instead of 30
    assert handler.client.get_sleep_data.call_count == 3
    # get_body_composition is called with a date range for recent weight records
    assert handler.client.get_body_composition.call_count == 1
    latest = db.get_latest_body_composition()
    assert latest is not None
    assert latest["weight_kg"] == 80.0
    assert latest["source"] == "Garmin"
    assert db.get_metadata("last_garmin_sync") == datetime.now().strftime("%Y-%m-%d")

