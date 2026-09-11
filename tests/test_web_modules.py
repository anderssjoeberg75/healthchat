"""Tests for the web layer's building blocks.

Covers the encrypted per-user store, the SQLite compatibility shim that lets
the account code run without MariaDB, the calorie backfill and the sync
orchestration's source selection. Nothing here touches the network.
"""

import os
import sys

import pytest

os.environ["MARIADB_HOST"] = ""
os.environ["MARIADB_PASSWORD"] = ""

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import crypto  # noqa: E402
import web_dbcompat  # noqa: E402
import web_metrics  # noqa: E402
import web_store  # noqa: E402
import web_sync  # noqa: E402


@pytest.fixture(autouse=True)
def _no_mariadb(monkeypatch):
    """Keep these tests on the SQLite fallback, whatever the machine holds.

    ``load_db_env`` copies ~/.healthchat/db.env over the environment on every
    ``GarminDatabase()``, so clearing the variables is not enough: on a machine
    that has real credentials there, each instantiation would spend its connect
    timeout reaching for a database these tests must not touch. Stubbing the
    loader keeps the run hermetic and fast.
    """
    import garmin_db

    monkeypatch.setattr(garmin_db, "load_db_env", lambda: None)
    monkeypatch.setenv("MARIADB_HOST", "")
    monkeypatch.setenv("MARIADB_PASSWORD", "")


class FakeSession:
    def __init__(self, dek=None):
        self.user_id = 1
        self.dek = dek
        self.encrypted_profile = {}


class FakeDb:
    """Just the metadata surface web_store uses."""

    def __init__(self):
        self.values = {}

    def get_metadata(self, key, default=None):
        return self.values.get(key, default)

    def set_metadata(self, key, value):
        self.values[key] = value


# --- encrypted per-user store ----------------------------------------------


def test_store_round_trips_a_value_without_a_key():
    db, session = FakeDb(), FakeSession(dek=None)

    web_store.write(db, session, "settings", {"a": 1, "b": "två"})

    assert web_store.read(db, session, "settings") == {"a": 1, "b": "två"}


def test_store_encrypts_when_a_key_is_available():
    db, session = FakeDb(), FakeSession(dek=crypto.generate_dek())

    web_store.write(db, session, "settings", {"api_key": "sk-secret"})

    stored = db.values["settings"]
    assert "sk-secret" not in stored, "the raw value must not be readable in storage"
    assert web_store.read(db, session, "settings") == {"api_key": "sk-secret"}


def test_a_different_key_cannot_read_the_value():
    db = FakeDb()
    web_store.write(db, FakeSession(dek=crypto.generate_dek()), "settings", {"api_key": "sk-secret"})

    other = web_store.read(db, FakeSession(dek=crypto.generate_dek()), "settings", default="locked")

    assert other == "locked"


def test_store_returns_the_default_for_a_missing_key():
    assert web_store.read(FakeDb(), FakeSession(), "nope", default=[]) == []


def test_store_survives_a_corrupt_value():
    db, session = FakeDb(), FakeSession(dek=crypto.generate_dek())
    db.values["settings"] = "enc:v1:{not json"

    assert web_store.read(db, session, "settings", default={}) == {}


# --- SQLite compatibility for the account tables ----------------------------


def test_sqlite_shim_speaks_the_pymysql_dialect(tmp_path):
    conn = web_dbcompat.connect(tmp_path / "users.db")

    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO users (email, password_hash, kdf_salt, wrapped_dek, dek_nonce) "
            "VALUES (%s, %s, %s, %s, %s)",
            ("a@b.se", "hash", b"salt", b"wrapped", b"nonce"),
        )
        user_id = cur.lastrowid
    conn.commit()

    with conn.cursor() as cur:
        cur.execute("SELECT email FROM users WHERE id = %s", (user_id,))
        assert cur.fetchone()[0] == "a@b.se"
    conn.close()


def test_sqlite_shim_enforces_unique_emails(tmp_path):
    conn = web_dbcompat.connect(tmp_path / "users.db")
    insert = ("INSERT INTO users (email, password_hash, kdf_salt, wrapped_dek, dek_nonce) "
              "VALUES (%s, %s, %s, %s, %s)")
    values = ("dup@b.se", "hash", b"s", b"w", b"n")

    with conn.cursor() as cur:
        cur.execute(insert, values)
    conn.commit()

    with pytest.raises(Exception) as excinfo:
        with conn.cursor() as cur:
            cur.execute(insert, values)

    assert web_dbcompat.is_duplicate_error(excinfo.value)
    conn.close()


def test_real_registration_works_over_sqlite(tmp_path):
    """The whole point of the shim: accounts without a MariaDB server."""
    import auth

    conn = web_dbcompat.connect(tmp_path / "users.db")
    user_id, recovery_key, session = auth.register_user(conn, "sqlite@example.com", "correct-horse-battery")

    assert user_id > 0
    assert recovery_key
    assert session.email == "sqlite@example.com"

    signed_in = auth.authenticate_user(conn, "sqlite@example.com", "correct-horse-battery")
    assert signed_in.user_id == user_id
    conn.close()


# --- calorie backfill -------------------------------------------------------

PROFILE = {"weight_kg": 80, "height_cm": 180, "age": 40, "sex": "male"}


def _sync_day(db, date, steps=0, bmr=0, workout=0, workout_steps=0):
    if steps or bmr:
        db.upsert_daily_summary(date, steps=steps, raw_data={"bmrKilocalories": bmr} if bmr else {})
    if workout or workout_steps:
        db.upsert_activity({
            "activityId": int(date.replace("-", "")),
            "startTimeLocal": f"{date} 07:00:00",
            "activityName": "Pass",
            "activityType": "running",
            "distance_km": 6,
            "duration_min": 35,
            "calories": workout,
            "steps": workout_steps,
        })


def test_backfill_fills_days_the_dashboard_never_saw(db, days_ago):
    _sync_day(db, days_ago(3), steps=9000, bmr=1800)
    _sync_day(db, days_ago(2), steps=4000, bmr=1800, workout=600)

    result = web_metrics.backfill_calorie_burn(db, PROFILE, days=30)

    written = {row["date"]: row for row in db.get_calorie_burn_history(30)}
    assert result["written"] == 2
    assert set(written) == {days_ago(3), days_ago(2)}
    assert written[days_ago(2)]["workout_burn"] == 600


def test_backfilled_days_count_a_full_day_of_rest(db, days_ago):
    _sync_day(db, days_ago(1), steps=1000, bmr=1800)

    web_metrics.backfill_calorie_burn(db, PROFILE, days=30)

    row = db.get_calorie_burn_history(30)[0]
    assert row["day_fraction"] == 1.0
    assert row["resting_burn"] == 1800  # not pro-rated like today's card


def test_backfill_never_touches_today(db, today_str, days_ago):
    _sync_day(db, today_str, steps=5000, bmr=1800)
    _sync_day(db, days_ago(1), steps=5000, bmr=1800)

    web_metrics.backfill_calorie_burn(db, PROFILE, days=30)

    assert [row["date"] for row in db.get_calorie_burn_history(30)] == [days_ago(1)]


def test_backfill_leaves_days_without_evidence_alone(db, days_ago):
    db.upsert_daily_summary(days_ago(2), steps=0)

    result = web_metrics.backfill_calorie_burn(db, PROFILE, days=30)

    assert result["written"] == 0 and result["skipped"] == 1
    assert db.get_calorie_burn_history(30) == []


def test_backfill_repairs_a_day_frozen_at_a_partial_value(db, days_ago):
    date = days_ago(2)
    _sync_day(db, date, steps=9000, bmr=1800)
    db.upsert_calorie_burn(date, total_burn=500, resting_burn=400, day_fraction=0.25)

    web_metrics.backfill_calorie_burn(db, PROFILE, days=30)

    repaired = db.get_calorie_burn_history(30)[0]
    assert repaired["day_fraction"] == 1.0
    assert repaired["resting_burn"] == 1800


def test_backfill_leaves_complete_days_alone_unless_overwrite(db, days_ago):
    date = days_ago(2)
    _sync_day(db, date, steps=9000, bmr=1800)
    db.upsert_calorie_burn(date, total_burn=1234, resting_burn=1234, day_fraction=1.0)

    assert web_metrics.backfill_calorie_burn(db, PROFILE, days=30)["written"] == 0
    assert db.get_calorie_burn_history(30)[0]["total_burn"] == 1234

    web_metrics.backfill_calorie_burn(db, PROFILE, days=30, overwrite=True)
    assert db.get_calorie_burn_history(30)[0]["resting_burn"] == 1800


def test_backfill_is_idempotent(db, days_ago):
    _sync_day(db, days_ago(2), steps=9000, bmr=1800)

    web_metrics.backfill_calorie_burn(db, PROFILE, days=30, overwrite=True)
    first = db.get_calorie_burn_history(30)
    web_metrics.backfill_calorie_burn(db, PROFILE, days=30, overwrite=True)
    second = db.get_calorie_burn_history(30)

    assert len(first) == len(second) == 1
    assert first[0]["total_burn"] == second[0]["total_burn"]


def test_workout_steps_are_deducted_from_everyday_steps(db, days_ago):
    date = days_ago(1)
    _sync_day(db, date, steps=12000, bmr=1800, workout=500, workout_steps=5000)

    web_metrics.backfill_calorie_burn(db, PROFILE, days=30)

    row = db.get_calorie_burn_history(30)[0]
    # 12000 total steps minus the 5000 walked during the workout.
    everyday = web_metrics.calorie_calc.step_burn(7000, 80)
    assert row["steps_burn"] == round(everyday)


def test_workout_steps_are_estimated_for_step_based_sports():
    activity = {"activity_type": "running", "distance_km": 10}

    assert web_metrics.workout_steps_of(activity) == 13000


def test_workout_steps_prefer_the_device_value():
    activity = {"activity_type": "running", "distance_km": 10, "raw_json": '{"steps": 9000}'}

    assert web_metrics.workout_steps_of(activity) == 9000


def test_calorie_snapshot_persists_today(db, today_str):
    db.upsert_daily_summary(today_str, steps=9000, raw_data={"bmrKilocalories": 900})

    result = web_metrics.calorie_snapshot(db, PROFILE, [])

    assert result["total_burn"] > 0
    assert db.get_calorie_burn_history(2), "today's row should be written"


# --- sync orchestration -----------------------------------------------------


class FakeWorkspace:
    def __init__(self, sources):
        self._sources = sources
        self.sync_status = {"text": "", "running": False, "done": False}
        self.status = {}

    def connected_sources(self):
        return self._sources


def test_selected_sources_lists_only_connected_ones():
    workspace = FakeWorkspace({"garmin": True, "fitbit": False, "withings": True, "strava": False})

    assert web_sync.selected_sources(workspace) == ["garmin", "withings"]


def test_selected_sources_can_be_narrowed_to_one():
    workspace = FakeWorkspace({"garmin": True, "fitbit": False, "withings": True, "strava": False})

    assert web_sync.selected_sources(workspace, only="withings") == ["withings"]
    assert web_sync.selected_sources(workspace, only="fitbit") == []


def test_checkin_reports_when_nothing_is_connected():
    workspace = FakeWorkspace({"garmin": False, "fitbit": False, "withings": False, "strava": False})

    assert web_sync.start_checkin(workspace)["reason"] == "no_sources"


def test_checkin_refuses_to_start_twice():
    workspace = FakeWorkspace({"garmin": True, "fitbit": False, "withings": False, "strava": False})
    workspace.sync_status = {"text": "", "running": True, "done": False}

    assert web_sync.start_checkin(workspace)["reason"] == "busy"


def test_checkin_day_counts_match_the_desktop_menus():
    assert web_sync.CHECKIN_DAYS == {"garmin": 30, "fitbit": 7, "withings": 365, "strava": 30}
    assert web_sync.FULL_DAYS["garmin"] == 3650
