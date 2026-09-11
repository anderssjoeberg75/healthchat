"""
Tests for GarminDatabase running against MariaDB with envelope encryption.
"""

import pytest
import pymysql
from garmin_db import GarminDatabase
import auth
import crypto

import os
import garmin_db

garmin_db.load_db_env()

TEST_DB_CONFIG = {
    "host": os.environ.get("MARIADB_HOST", "192.168.101.106"),
    "port": int(os.environ.get("MARIADB_PORT", 3306)),
    "user": os.environ.get("MARIADB_USER", "healthchat"),
    "password": os.environ.get("MARIADB_PASSWORD", ""),
    "database": os.environ.get("MARIADB_DB", "healthchat"),
    "charset": "utf8mb4"
}

@pytest.fixture
def mariadb_env():
    try:
        conn = pymysql.connect(**TEST_DB_CONFIG)
    except Exception as e:
        pytest.skip(f"MariaDB not reachable: {e}")

    test_email = "test_mariadb_db@andrix.se"
    with conn.cursor() as cur:
        cur.execute("DELETE FROM users WHERE email = %s", (test_email,))
        conn.commit()

    user_id, rec_key, session = auth.register_user(conn, test_email, "TestPassword123!")

    db = GarminDatabase(mariadb_config=TEST_DB_CONFIG, user_id=user_id, dek=session.dek)

    yield conn, user_id, session, db

    # Teardown
    try:
        auth.delete_user_account(conn, user_id)
        conn.close()
    except Exception:
        pass

def test_mariadb_encrypted_daily_summary(mariadb_env):
    conn, user_id, session, db = mariadb_env

    # Upsert daily summary
    test_date = "2026-09-01"
    db.upsert_daily_summary(test_date, steps=10450, calories=2300, active_calories=550, resting_hr=58)

    # Read back through database manager
    summary = db.get_daily_summary(test_date)
    assert summary is not None
    assert summary["total_steps"] == 10450
    assert summary["total_calories"] == 2300
    assert summary["resting_hr"] == 58

    # Verify directly in MariaDB that ciphertext is unreadable/encrypted
    with conn.cursor() as cur:
        cur.execute("SELECT encrypted_payload FROM daily_summary WHERE user_id = %s AND date = %s", (user_id, test_date))
        row = cur.fetchone()
        assert row is not None
        ciphertext = row[0]
        # Verify plain text strings like '10450' or 'total_steps' are NOT visible in ciphertext
        assert b"10450" not in ciphertext
        assert b"total_steps" not in ciphertext

def test_mariadb_user_isolation(mariadb_env):
    conn, user_id1, session1, db1 = mariadb_env

    # Register user 2
    user_id2, _, session2 = auth.register_user(conn, "user2_iso@andrix.se", "Password2222!")
    db2 = GarminDatabase(mariadb_config=TEST_DB_CONFIG, user_id=user_id2, dek=session2.dek)

    # User 1 writes sleep data
    db1.upsert_sleep("2026-09-02", total_hours=7.5, score=85)

    # User 2 reads sleep history: should be empty!
    u2_sleep = db2.get_sleep_history(days=30)
    assert len(u2_sleep) == 0

    # User 1 reads sleep history: should have 1 item!
    u1_sleep = db1.get_sleep_history(days=30)
    assert len(u1_sleep) == 1
    assert u1_sleep[0]["total_sleep_hours"] == 7.5

    auth.delete_user_account(conn, user_id2)

def test_mariadb_activities_and_cascade_delete(mariadb_env):
    conn, user_id, session, db = mariadb_env

    # Insert activity
    db.upsert_activity({
        "activityId": 99887766,
        "activityName": "Morgonjogg",
        "activityType": "running",
        "startTimeLocal": "2026-09-03 07:00:00",
        "distance_km": 6.2,
        "duration_min": 35.0,
        "calories": 420
    })

    acts = db.get_activities_history(days=30)
    assert len(acts) == 1
    assert acts[0]["activity_name"] == "Morgonjogg"
    assert acts[0]["distance_km"] == 6.2

    # Delete user account: verify cascading delete removes activity row in MariaDB
    auth.delete_user_account(conn, user_id)
    with conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM activities WHERE user_id = %s", (user_id,))
        count = cur.fetchone()[0]
        assert count == 0
