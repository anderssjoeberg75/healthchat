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
