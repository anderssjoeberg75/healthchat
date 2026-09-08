"""Tests for the chart/metric logic ported from the desktop charts view."""

import json
import os
import tempfile

os.environ.setdefault("HEALTHCHAT_DATA_DIR", tempfile.mkdtemp(prefix="healthchat-test-"))

from webapp.backend import charts, metrics  # noqa: E402


# --- prepare_chart_series ---------------------------------------------------


def test_series_is_sorted_and_labelled_without_the_year_inside_one_year():
    rows = [
        {"date": "2026-03-02", "distance_km": 5},
        {"date": "2026-03-01", "distance_km": 10},
    ]

    labels, values = charts.prepare_chart_series(rows, "distance_km")

    assert labels == ["03-01", "03-02"]
    assert values == [10.0, 5.0]


def test_series_keeps_the_year_when_the_range_spans_two_years():
    rows = [{"date": "2025-12-31", "distance_km": 1}, {"date": "2026-01-01", "distance_km": 2}]

    labels, _ = charts.prepare_chart_series(rows, "distance_km")

    assert labels == ["25-12-31", "26-01-01"]


def test_series_handles_missing_values_and_empty_input():
    assert charts.prepare_chart_series([], "x") == ([], [])
    assert charts.prepare_chart_series([{"date": "2026-01-01"}], "x", default_val=3.0) == (["01-01"], [3.0])


def test_series_falls_back_to_start_time_when_date_is_absent():
    labels, values = charts.prepare_chart_series([{"start_time": "2026-05-04 07:00:00", "calories": 300}], "calories")

    assert labels == ["05-04"]
    assert values == [300.0]


# --- rendering --------------------------------------------------------------


def test_every_figure_renders_even_with_no_data(db):
    assert charts.render_weekly_activity([])[:4] == b"\x89PNG"
    assert charts.render_bb_sleep_stress([], [], [])[:4] == b"\x89PNG"
    assert charts.render_evolab(db, 30, [], [], [], [], [], None, [])[:4] == b"\x89PNG"


# --- activity table ---------------------------------------------------------


def test_activity_rows_are_sorted_newest_first_and_formatted():
    rows = metrics.activity_rows(
        [
            {"date": "2026-01-01", "activity_name": "Old", "distance_km": 5, "duration_min": 30, "calories": 300, "avg_hr": 140},
            {"date": "2026-02-01", "activity_name": "New", "distance_km": 10.256, "duration_min": 60.44, "calories": "500", "avg_hr": 150.6},
        ]
    )

    assert [row["name"] for row in rows] == ["New", "Old"]
    assert rows[0]["distance"] == "10.26"
    assert rows[0]["duration"] == "60.4"
    assert rows[0]["calories"] == 500
    assert rows[0]["hr"] == 150


def test_activity_source_is_detected_from_the_raw_payload():
    strava = metrics.activity_rows([{"date": "2026-01-01", "raw_json": json.dumps({"athlete": {"id": 1}})}])
    fitbit = metrics.activity_rows([{"date": "2026-01-01", "raw_json": json.dumps({"logId": 7})}])
    garmin = metrics.activity_rows([{"date": "2026-01-01", "raw_json": json.dumps({"activityId": 1})}])

    assert strava[0]["source"] == "Strava"
    assert fitbit[0]["source"] == "Fitbit"
    assert garmin[0]["source"] == "Garmin"


def test_activity_rows_handle_an_empty_history():
    assert metrics.activity_rows([]) == []


# --- dashboard cards --------------------------------------------------------


def test_fitness_index_defaults_to_70_without_activities(db):
    cards = metrics.dashboard_cards(db, {}, [], [], [], [], None)

    assert cards["fitness"]["value"] == "70.0"
    assert cards["fitness"]["subtitle"] == "Beräknat från 0 träningspass & pulszoner"


def test_fitness_index_stays_inside_its_bounds(db):
    fast = [{"distance_km": 40, "duration_min": 60, "avg_hr": 100}]
    slow = [{"distance_km": 0.1, "duration_min": 300, "avg_hr": 190}]

    assert float(metrics.dashboard_cards(db, {}, [], [], [], fast, None)["fitness"]["value"]) <= 99.0
    assert float(metrics.dashboard_cards(db, {}, [], [], [], slow, None)["fitness"]["value"]) >= 45.0


def test_recovery_card_flags_a_high_body_battery(db):
    high = metrics.dashboard_cards(db, {}, [], [{"highest": 90}], [], [], None)["recovery"]
    low = metrics.dashboard_cards(db, {}, [], [{"highest": 40}], [], [], None)["recovery"]

    assert high["value"] == "90%" and high["positive"] is True
    assert low["value"] == "40%" and low["positive"] is False


def test_weight_card_uses_the_latest_measurement(db):
    body_comp = {"weight_kg": 81.25, "fat_ratio_pct": 19.4, "muscle_mass_kg": 63.1, "source": "withings", "date": "2026-02-01"}

    card = metrics.dashboard_cards(db, {}, [], [], [], [], body_comp)["weight"]

    assert card["value"] == "81.2 kg"
    assert "Fett: 19.4%" in card["subtitle"]
    assert card["source"] == "Källa: Withings (2026-02-01)"


def test_calorie_card_reports_no_data_without_a_profile(db):
    card = metrics.calorie_card(db, {}, None, [])

    assert card["empty"] == "Ingen data ännu"


def test_calorie_card_sums_rest_steps_and_workouts_and_persists_the_day(db, today_str):
    db.upsert_daily_summary(today_str, steps=9000, raw_data={"bmrKilocalories": 1800})
    profile = {"weight_kg": 80, "height_cm": 180, "age": 40, "sex": "male"}
    activities = [{"date": today_str, "calories": 500}]

    card = metrics.calorie_card(db, profile, None, activities)

    assert "kcal" in card["total"]
    assert card["workout"].startswith("🏋️ Träning: 500 kcal")
    assert card["note"] == "Vilo-BMR från Garmin"
    assert db.get_calorie_burn_history(2), "today's burn should be written to the database"
