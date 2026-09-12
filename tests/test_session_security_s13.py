"""
Unit tests for S-13 (Väg A): In-memory session handling and DEK protection.
- DEK is never stored in persistent DB (user_sessions has no dek column).
- Expired sessions are rejected and zeroized in memory.
- cleanup_expired_sessions purges expired sessions from memory and DB.
"""

import sqlite3
import os
import time
from auth import UserSession
from server import (
    init_sessions_table,
    save_session_to_db,
    load_session_from_db,
    store_active_session,
    remove_active_session,
    get_valid_session,
    cleanup_expired_sessions,
    _active_sessions,
    _session_expirations
)


def test_user_sessions_table_has_no_dek_column():
    """Verify that user_sessions table does not contain a dek or encrypted_profile column."""
    conn = sqlite3.connect(":memory:")
    init_sessions_table(conn)

    cursor = conn.execute("PRAGMA table_info(user_sessions)")
    columns = [row[1] for row in cursor.fetchall()]

    assert "session_id" in columns
    assert "user_id" in columns
    assert "email" in columns
    assert "created_at" in columns
    assert "expires_at" in columns
    assert "dek" not in columns
    assert "encrypted_profile" not in columns


def test_session_expiry_zeroes_dek_in_memory():
    """Verify that an expired session returns None and the DEK is wiped."""
    session_id = "test-expiry-session"
    dek = bytearray(os.urandom(32))
    session = UserSession(user_id=1, email="exp@test.com", dek=dek)

    # Store with max_age = -10 seconds (already expired)
    store_active_session(session_id, session, max_age=-10)

    # get_valid_session should return None and remove/clear it
    retrieved = get_valid_session(session_id)
    assert retrieved is None
    assert session_id not in _active_sessions
    assert session_id not in _session_expirations

    # Verify session DEK was zeroized
    assert all(b == 0 for b in session.dek)


def test_cleanup_expired_sessions_cleans_memory_and_db():
    """Verify that cleanup_expired_sessions purges expired rows from DB and memory."""
    conn = sqlite3.connect(":memory:")
    init_sessions_table(conn)

    # Valid session
    valid_sid = "sid-valid"
    s_valid = UserSession(user_id=10, email="val@test.com", dek=bytearray(os.urandom(32)))
    store_active_session(valid_sid, s_valid, max_age=3600)
    save_session_to_db(conn, valid_sid, s_valid, max_age=3600)

    # Expired session
    exp_sid = "sid-expired"
    s_exp = UserSession(user_id=20, email="exp2@test.com", dek=bytearray(os.urandom(32)))
    store_active_session(exp_sid, s_exp, max_age=-10)
    save_session_to_db(conn, exp_sid, s_exp, max_age=-10)

    # Run cleanup
    cleanup_expired_sessions(conn)

    # Verify memory
    assert valid_sid in _active_sessions
    assert exp_sid not in _active_sessions
    assert all(b == 0 for b in s_exp.dek)

    # Verify DB
    cursor = conn.execute("SELECT session_id FROM user_sessions")
    db_sids = [r[0] for r in cursor.fetchall()]
    assert valid_sid in db_sids
    assert exp_sid not in db_sids

    # Cleanup memory
    remove_active_session(valid_sid)
