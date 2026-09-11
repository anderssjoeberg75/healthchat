"""
Unit tests for security hardening (S-5, S-6, S-8, S-9, S-11) and performance optimizations (PF-3, PF-4, PF-7).
"""

import time
import logging
import pytest
from garmin_db import GarminDatabase, _ALLOWED_TABLES
from auth import UserSession, verify_password, password_needs_rehash, mask_email, logout_user


def test_user_session_dek_zeroing():
    """S-6: Test that UserSession.clear() zeroes out DEK bytearray in memory."""
    dek = bytearray(b"0123456789abcdef0123456789abcdef")
    session = UserSession(user_id=42, email="user@example.com", dek=dek)
    
    assert len(session.dek) == 32
    assert session.dek[0] != 0
    
    session.clear()
    assert all(b == 0 for b in session.dek)
    assert all(b == 0 for b in dek)  # Same reference in memory


def test_logout_user_clears_session_dek():
    """S-6: Test that logout_user calls session.clear()."""
    dek = bytearray(b"secret_dek_key_32_bytes_long!!!!")
    session = UserSession(user_id=1, email="testlogout@example.com", dek=dek)
    
    logout_user("testlogout@example.com", session=session)
    assert all(b == 0 for b in session.dek)


def test_verify_password_and_rehash():
    """S-8: Test verify_password handling invalid hashes and checking rehash status."""
    valid_hash = "$argon2id$v=19$m=65536,t=2,p=1$c2FsdHNhbHQ$hashhashhashhashhashhashhashhashhashhashhash"
    corrupt_hash = "invalid_hash_string_not_argon2"
    
    assert verify_password(corrupt_hash, "password123") is False
    assert password_needs_rehash(corrupt_hash) is True


def test_mask_email():
    """S-9: Test email PII masking function."""
    assert mask_email("anders@andrix.se") == "a****s@andrix.se"
    assert mask_email("john.doe@domain.org") == "j******e@domain.org"
    assert mask_email("ab@c.com") == "a*@c.com"
    assert mask_email("invalid_email") == "***"
    assert mask_email("") == "***"


def test_table_name_whitelist():
    """S-11: Test that SQL table name whitelist prevents untrusted table interpolation."""
    db = GarminDatabase()
    db.is_mariadb = True
    db.user_id = 1
    db.dek = bytearray(b"0123456789abcdef0123456789abcdef")
    
    bad_table = "users; DROP TABLE users;"
    
    with pytest.raises(ValueError, match="otillåtet tabellnamn"):
        db._mariadb_get_history(bad_table, 30)
        
    with pytest.raises(ValueError, match="otillåtet tabellnamn"):
        db._mariadb_upsert_payload(bad_table, "2026-09-11", {})


def test_deduplicate_activities_performance_and_merging():
    """PF-3: Test that deduplicate_activities handles 1000 activities fast and correctly merges duplicates."""
    activities = []
    # Create 500 distinct activities across 100 days
    for day in range(100):
        date_str = f"2026-{(day // 28) + 1:02d}-{(day % 28) + 1:02d}"
        for i in range(5):
            activities.append({
                "activityId": f"act_{day}_{i}",
                "date": date_str,
                "distance_km": 10.0 + i,
                "duration_min": 50.0 + i,
                "avg_hr": 150.0,
                "source": "Garmin",
                "calories": 600
            })
            # Add a duplicate from Strava for the same activity
            activities.append({
                "activityId": f"act_{day}_{i}_strava",
                "date": date_str,
                "distance_km": 10.02 + i,  # slight diff
                "duration_min": 50.1 + i,
                "avg_hr": 150.0,
                "source": "Strava",
                "calories": 605
            })

    assert len(activities) == 1000

    start_t = time.time()
    deduped = GarminDatabase.deduplicate_activities(activities)
    elapsed_ms = (time.time() - start_t) * 1000

    assert len(deduped) == 500
    assert elapsed_ms < 200.0  # Must run well under 200ms
    assert "Garmin / Strava" in deduped[0]["source"] or "Strava" in deduped[0]["source"]


def test_normalize_date_strict_mode_and_warning(caplog):
    """PF-7: Test date normalization strict mode and warning logging."""
    assert GarminDatabase._normalize_date("2026-09-11") == "2026-09-11"
    assert GarminDatabase._normalize_date("11/09/2026") == "2026-09-11"
    
    with pytest.raises(ValueError):
        GarminDatabase._normalize_date("invalid_date_abc", strict=True)

    with caplog.at_level(logging.WARNING):
        result = GarminDatabase._normalize_date("invalid_date_abc", strict=False)
        assert "Okänt datumformat" in caplog.text
        assert len(result) == 10
