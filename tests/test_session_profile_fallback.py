"""
Unit test for B-4: load_session_from_db profile fallback from users table.
"""

import sqlite3
import os
import crypto
from server import init_sessions_table, load_session_from_db


def test_load_session_from_db_decrypts_profile_from_users_table():
    """Verify that when user_sessions has no encrypted_profile, it falls back to decrypting from users table."""
    conn = sqlite3.connect(":memory:")
    init_sessions_table(conn)

    conn.execute("""
        CREATE TABLE users (
            id INTEGER PRIMARY KEY,
            email TEXT UNIQUE,
            encrypted_profile BLOB,
            profile_nonce BLOB
        )
    """)

    uid = 42
    email = "testfallback@example.com"
    dek = os.urandom(32)
    profile_data = {"age": 35, "height_cm": 182.0, "weight_kg": 78.5, "sex": "male"}
    nonce, ciphertext = crypto.encrypt_payload(dek, profile_data)

    conn.execute(
        "INSERT INTO users (id, email, encrypted_profile, profile_nonce) VALUES (?, ?, ?, ?)",
        (uid, email, ciphertext, nonce)
    )

    # S-13: DEK is stored in-memory, user_sessions stores session metadata with expires_at
    from datetime import datetime, timezone, timedelta
    from auth import UserSession
    from server import store_active_session, save_session_to_db

    session_id = "test-session-fallback-123"
    # Store session in memory with empty profile
    mem_session = UserSession(user_id=uid, email=email, dek=bytearray(dek), encrypted_profile=None)
    store_active_session(session_id, mem_session, max_age=3600)
    save_session_to_db(conn, session_id, mem_session, max_age=3600)

    session = load_session_from_db(conn, session_id)
    assert session is not None
    assert session.user_id == uid
    assert session.email == email
    assert session.encrypted_profile == profile_data
    assert session.encrypted_profile["age"] == 35
    assert session.encrypted_profile["weight_kg"] == 78.5
