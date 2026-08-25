"""Tests for garmin_db.GarminDatabase (local SQLite cache).

These are fully offline and deterministic: every test uses a throwaway
database file provided by the `db` fixture in conftest.py.
"""

import json
import sqlite3

import pytest

from garmin_db import GarminDatabase


# --- Schema / initialization ---------------------------------------------------

def test_init_creates_all_tables(db):
    with db.get_connection() as conn:
        rows = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    tables = {row["name"] for row in rows}
    for expected in {
        "daily_summary",
        "sleep_data",
        "body_battery",
        "stress_data",
        "hrv_data",
        "activities",
    }:
        assert expected in tables


def test_init_is_idempotent(tmp_path):
    path = tmp_path / "repeat.db"
    GarminDatabase(db_path=path)
    # Re-opening the same path must not raise (CREATE TABLE IF NOT EXISTS).
    GarminDatabase(db_path=path)


def test_connection_uses_row_factory(db):
    with db.get_connection() as conn:
        assert conn.row_factory is sqlite3.Row


# --- Daily summary -------------------------------------------------------------

def test_upsert_daily_summary_stores_and_serializes_raw(db, today_str):
    db.upsert_daily_summary(
        today_str, steps=8500, calories=2200, active_calories=600,
        resting_hr=52, raw_data={"source": "unit-test"},
    )
    with db.get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM daily_summary WHERE date = ?", (today_str,)
        ).fetchone()
    assert row["total_steps"] == 8500
    assert row["resting_hr"] == 52
    assert json.loads(row["raw_json"]) == {"source": "unit-test"}


def test_upsert_daily_summary_updates_existing_row(db, today_str):
    db.upsert_daily_summary(today_str, steps=100)
    db.upsert_daily_summary(today_str, steps=999)
    with db.get_connection() as conn:
        rows = conn.execute(
            "SELECT total_steps FROM daily_summary WHERE date = ?", (today_str,)
        ).fetchall()
    assert len(rows) == 1  # upsert, not a second insert
    assert rows[0]["total_steps"] == 999


# --- Sleep ---------------------------------------------------------------------

def test_upsert_and_read_sleep_history(db, today_str):
    db.upsert_sleep(
        today_str, total_hours=7.5, deep_hours=1.5, light_hours=4.0,
        rem_hours=1.8, awake_hours=0.2, score=88,
    )
    history = db.get_sleep_history(days=7)
    assert len(history) == 1
    entry = history[0]
    assert entry["date"] == today_str
    assert entry["total_sleep_hours"] == pytest.approx(7.5)
    assert entry["sleep_score"] == 88


def test_get_sleep_history_excludes_old_dates(db, days_ago):
    db.upsert_sleep(days_ago(2), total_hours=8.0)
    db.upsert_sleep(days_ago(60), total_hours=6.0)
    history = db.get_sleep_history(days=30)
    dates = {row["date"] for row in history}
    assert days_ago(2) in dates
    assert days_ago(60) not in dates


def test_sleep_history_ordered_ascending(db, days_ago):
    db.upsert_sleep(days_ago(1), total_hours=7.0)
    db.upsert_sleep(days_ago(5), total_hours=6.0)
    db.upsert_sleep(days_ago(3), total_hours=8.0)
    dates = [row["date"] for row in db.get_sleep_history(days=30)]
    assert dates == sorted(dates)


# --- Body battery / stress / HRV ----------------------------------------------

def test_upsert_body_battery(db, today_str):
    db.upsert_body_battery(today_str, charged=80, drained=60, highest=95,
                           lowest=15, current=40)
    history = db.get_body_battery_history(days=7)
    assert len(history) == 1
    assert history[0]["highest"] == 95
    assert history[0]["current"] == 40


def test_upsert_stress_maps_max_stress_column(db, today_str):
    # The method arg is `max_stress` but the column is `max`.
    db.upsert_stress(today_str, average=30, max_stress=88, rest=20,
                     activity=45, low_min=120, med_min=30, high_min=5)
    history = db.get_stress_history(days=7)
    assert len(history) == 1
    assert history[0]["max"] == 88
    assert history[0]["low_duration_min"] == 120


def test_upsert_hrv(db, today_str):
    db.upsert_hrv(today_str, last_night_avg=65.5, weekly_avg=62.1,
                  status="BALANCED")
    history = db.get_hrv_history(days=7)
    assert len(history) == 1
    assert history[0]["last_night_avg"] == pytest.approx(65.5)
    assert history[0]["status"] == "BALANCED"


# --- Activities ----------------------------------------------------------------

def _sample_activity(**overrides):
    activity = {
        "activityId": 12345,
        "activityName": "Morning Run",
        "activityType": {"typeKey": "running"},
        "startTimeLocal": "2026-02-16 06:20:00",
        "distance": 3250.0,        # meters -> 3.25 km
        "duration": 1140.0,        # seconds -> 19 min
        "calories": 202,
        "averageHR": 150,
        "maxHR": 172,
        "averageSpeed": 2.78,      # m/s -> ~6:00 min/km
    }
    activity.update(overrides)
    return activity


def test_upsert_activity_converts_units(db):
    db.upsert_activity(_sample_activity())
    history = db.get_activities_history(days=3650)
    assert len(history) == 1
    row = history[0]
    assert row["activity_id"] == 12345
    assert row["activity_type"] == "running"
    assert row["date"] == "2026-02-16"
    assert row["distance_km"] == pytest.approx(3.25)
    assert row["duration_min"] == pytest.approx(19.0)


def test_upsert_activity_computes_pace(db):
    db.upsert_activity(_sample_activity())
    row = db.get_activities_history(days=3650)[0]
    # pace = 1000 / (avg_speed_ms * 60) = 1000 / (2.78 * 60)
    assert row["avg_pace_min_km"] == pytest.approx(1000 / (2.78 * 60), rel=1e-6)


def test_upsert_activity_zero_speed_gives_zero_pace(db):
    db.upsert_activity(_sample_activity(activityId=999, averageSpeed=0))
    row = [r for r in db.get_activities_history(days=3650)
           if r["activity_id"] == 999][0]
    assert row["avg_pace_min_km"] == 0


def test_upsert_activity_without_id_is_ignored(db):
    db.upsert_activity({"activityName": "No ID activity"})
    assert db.get_activities_history(days=3650) == []


def test_upsert_activity_updates_existing(db):
    db.upsert_activity(_sample_activity(calories=202))
    db.upsert_activity(_sample_activity(calories=250))
    history = db.get_activities_history(days=3650)
    assert len(history) == 1
    assert history[0]["calories"] == 250


def test_upsert_activity_handles_missing_optional_fields(db):
    # Only the id + type present; numeric fields default to 0 without raising.
    db.upsert_activity({
        "activityId": 42,
        "activityType": {"typeKey": "walking"},
    })
    row = db.get_activities_history(days=3650)[0]
    assert row["activity_id"] == 42
    assert row["distance_km"] == 0
    assert row["calories"] == 0


# --- Empty-state queries -------------------------------------------------------

@pytest.mark.parametrize("query", [
    "get_sleep_history",
    "get_body_battery_history",
    "get_stress_history",
    "get_hrv_history",
    "get_activities_history",
])
def test_history_queries_empty_by_default(db, query):
    assert getattr(db, query)(days=30) == []


def test_deduplicate_activities_merges_duplicates(db):
    db.upsert_activity({
        "activityId": 101,
        "activityName": "Morgonlöpning",
        "startTimeLocal": "2026-08-19 08:00:00",
        "distance": 10000,
        "duration": 3000,
        "source": "Garmin"
    })
    db.upsert_activity({
        "activityId": 202,
        "activityName": "Morning Run",
        "startTimeLocal": "2026-08-19 08:00:00",
        "distance": 10050,
        "duration": 3010,
        "source": "Strava"
    })
    
    act_all = db.get_activities_history(days=30, deduplicate=False)
    assert len(act_all) == 2

    act_dedup = db.get_activities_history(days=30, deduplicate=True)
    assert len(act_dedup) == 1
    assert "Garmin" in act_dedup[0]["source"]
    assert "Strava" in act_dedup[0]["source"]


def test_sync_metadata_get_and_set(db):
    assert db.get_metadata("last_garmin_sync") is None
    assert db.get_metadata("last_garmin_sync", default="fallback") == "fallback"

    db.set_metadata("last_garmin_sync", "2026-08-25")
    assert db.get_metadata("last_garmin_sync") == "2026-08-25"

    db.set_metadata("last_garmin_sync", "2026-08-26")
    assert db.get_metadata("last_garmin_sync") == "2026-08-26"

