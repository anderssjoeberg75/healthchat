"""Tests for sleep score calculation and automatic fallback during Garmin sync."""

import time
from unittest.mock import MagicMock
import pytest
from garmin_handler import GarminDataHandler


def test_calculate_sleep_score_zero_and_invalid():
    # 0 hours sleep
    assert GarminDataHandler.calculate_sleep_score(0) == 0
    assert GarminDataHandler.calculate_sleep_score(-2.0) == 0
    # None/invalid inputs
    assert GarminDataHandler.calculate_sleep_score(None) == 0
    assert GarminDataHandler.calculate_sleep_score("invalid") == 0


def test_calculate_sleep_score_optimal_with_stages_and_bb():
    # 8.0h sleep, 1.5h deep (18.75%), 1.8h REM (22.5%), 0.3h awake, 60 Body Battery charged
    score = GarminDataHandler.calculate_sleep_score(
        total_hours=8.0,
        deep_hours=1.5,
        light_hours=4.7,
        rem_hours=1.8,
        awake_hours=0.3,
        body_battery_charged=60
    )
    assert 90 <= score <= 100


def test_calculate_sleep_score_short_sleep():
    # 4.0h sleep, low deep, low REM, high awake
    score = GarminDataHandler.calculate_sleep_score(
        total_hours=4.0,
        deep_hours=0.3,
        light_hours=2.5,
        rem_hours=0.4,
        awake_hours=0.8,
        avg_stress=40
    )
    assert score < 50


def test_calculate_sleep_score_awake_penalty():
    # Good sleep duration but very fragmented (awake 2 hours out of 9 total in bed)
    good_continuity = GarminDataHandler.calculate_sleep_score(
        total_hours=7.5,
        deep_hours=1.3,
        light_hours=4.5,
        rem_hours=1.7,
        awake_hours=0.2
    )
    bad_continuity = GarminDataHandler.calculate_sleep_score(
        total_hours=7.5,
        deep_hours=1.3,
        light_hours=4.5,
        rem_hours=1.7,
        awake_hours=2.0
    )
    assert good_continuity > bad_continuity + 10


def test_calculate_sleep_score_without_stages_device():
    # Older Garmin watch without sleep stages (only duration + awake)
    score = GarminDataHandler.calculate_sleep_score(
        total_hours=7.8,
        deep_hours=0.0,
        light_hours=0.0,
        rem_hours=0.0,
        awake_hours=0.3,
        body_battery_charged=50
    )
    # Should reweight duration and awake gracefully, not score 0
    assert 85 <= score <= 100


def test_calculate_sleep_score_stress_vs_bb():
    # Low stress gives higher score than high stress
    low_stress_score = GarminDataHandler.calculate_sleep_score(
        total_hours=7.0,
        deep_hours=1.0,
        light_hours=4.5,
        rem_hours=1.5,
        awake_hours=0.3,
        avg_stress=12
    )
    high_stress_score = GarminDataHandler.calculate_sleep_score(
        total_hours=7.0,
        deep_hours=1.0,
        light_hours=4.5,
        rem_hours=1.5,
        awake_hours=0.3,
        avg_stress=55
    )
    assert low_stress_score > high_stress_score


def test_sync_garmin_history_calculates_sleep_score_when_zero(db, days_ago):
    """Verify that sync_garmin_history calculates sleep score when Garmin returns 0."""
    handler = GarminDataHandler.__new__(GarminDataHandler)
    handler._authenticated = True
    handler.db = db
    handler.client = MagicMock()
    handler._ensure_display_name = MagicMock()
    handler.get_activities = MagicMock(return_value=[])

    target_date = days_ago(1)

    # Mock Garmin responses: device has no Sleep Score (score = 0)
    handler.client.get_sleep_data = MagicMock(return_value={
        "dailySleepDTO": {
            "calendarDate": target_date,
            "sleepTimeSeconds": 7.5 * 3600,
            "deepSleepSeconds": 1.4 * 3600,
            "lightSleepSeconds": 4.5 * 3600,
            "remSleepSeconds": 1.6 * 3600,
            "awakeSleepSeconds": 0.25 * 3600,
            "sleepScores": {
                "overall": {
                    "value": 0
                }
            }
        }
    })
    handler.client.get_body_battery = MagicMock(return_value=[
        {"charged": 55, "drained": 60, "highest": 80, "lowest": 20, "current": 40}
    ])
    handler.client.get_stress_data = MagicMock(return_value={
        "avgStressLevel": 18
    })
    handler.client.get_hrv_data = MagicMock(return_value={})
    handler.client.get_user_summary = MagicMock(return_value={})
    handler.client.get_body_composition = MagicMock(return_value={})
    handler.client.get_userprofile_settings = MagicMock(return_value={})
    handler.client.get_user_profile = MagicMock(return_value={})
    handler.client.get_heart_rate_zones = MagicMock(return_value={})

    # Trigger sync
    done = []
    handler.sync_garmin_history(days=2, force_full=True, on_complete=lambda: done.append(True))

    # Wait for the background worker thread to complete
    for _ in range(50):
        if done:
            break
        time.sleep(0.05)

    assert len(done) == 1

    # Check database
    sleep_hist = db.get_sleep_history(days=5)
    assert len(sleep_hist) >= 1
    record = next((r for r in sleep_hist if r["date"] == target_date), None)
    assert record is not None
    # Score should be calculated (not 0!)
    calc_score = record.get("sleep_score") or record.get("score")
    assert calc_score > 0
    assert calc_score >= 85


def test_sync_garmin_history_preserves_native_sleep_score(db, days_ago):
    """Verify that sync_garmin_history preserves native Garmin score when present."""
    handler = GarminDataHandler.__new__(GarminDataHandler)
    handler._authenticated = True
    handler.db = db
    handler.client = MagicMock()
    handler._ensure_display_name = MagicMock()
    handler.get_activities = MagicMock(return_value=[])

    target_date = days_ago(1)

    # Watch WITH native Firstbeat sleep score (score = 88)
    handler.client.get_sleep_data = MagicMock(return_value={
        "dailySleepDTO": {
            "calendarDate": target_date,
            "sleepTimeSeconds": 7.0 * 3600,
            "deepSleepSeconds": 1.0 * 3600,
            "lightSleepSeconds": 4.5 * 3600,
            "remSleepSeconds": 1.5 * 3600,
            "awakeSleepSeconds": 0.3 * 3600,
            "sleepScores": {
                "overall": {
                    "value": 88
                }
            }
        }
    })
    handler.client.get_body_battery = MagicMock(return_value=[])
    handler.client.get_stress_data = MagicMock(return_value={})
    handler.client.get_hrv_data = MagicMock(return_value={})
    handler.client.get_user_summary = MagicMock(return_value={})
    handler.client.get_body_composition = MagicMock(return_value={})
    handler.client.get_userprofile_settings = MagicMock(return_value={})
    handler.client.get_user_profile = MagicMock(return_value={})
    handler.client.get_heart_rate_zones = MagicMock(return_value={})

    done = []
    handler.sync_garmin_history(days=2, force_full=True, on_complete=lambda: done.append(True))

    for _ in range(50):
        if done:
            break
        time.sleep(0.05)

    assert len(done) == 1

    sleep_hist = db.get_sleep_history(days=5)
    record = next((r for r in sleep_hist if r["date"] == target_date), None)
    assert record is not None
    assert (record.get("sleep_score") or record.get("score")) == 88


def test_recalculate_stored_sleep_scores(db, days_ago):
    """Test retroactive recalculation of sleep score for existing database records."""
    handler = GarminDataHandler.__new__(GarminDataHandler)
    handler.db = db

    d1 = days_ago(2)
    # Upsert sleep with score=0
    db.upsert_sleep(date=d1, total_hours=7.5, deep_hours=1.5, light_hours=4.5, rem_hours=1.5, awake_hours=0.3, score=0)
    db.upsert_body_battery(date=d1, charged=50, drained=50, highest=80, lowest=30, current=50)

    # Ensure initial score is 0
    hist = db.get_sleep_history(days=5)
    assert hist[0]["sleep_score"] == 0

    # Recalculate
    updated = handler.recalculate_stored_sleep_scores(days=5)
    assert updated == 1

    hist_after = db.get_sleep_history(days=5)
    assert hist_after[0]["sleep_score"] > 80
