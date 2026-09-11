"""
Tests for auth.py authentication, Argon2id, and recovery workflows.
"""

import pytest
import pymysql
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
def db_conn():
    try:
        conn = pymysql.connect(**TEST_DB_CONFIG)
        yield conn
        conn.close()
    except Exception as e:
        pytest.skip(f"MariaDB not reachable: {e}")

def test_password_hash_and_verify():
    pwd = "SecretPassword123"
    hashed = auth.hash_password(pwd)
    assert auth.verify_password(hashed, pwd) is True
    assert auth.verify_password(hashed, "WrongPassword") is False

def test_register_and_authenticate(db_conn):
    test_email = "test_user_auth@andrix.se"
    test_pwd = "MyStrongPassword123!"

    # Clean up test user if exists
    with db_conn.cursor() as cur:
        cur.execute("DELETE FROM users WHERE email = %s", (test_email,))
        db_conn.commit()

    # Register
    user_id, rec_key, session = auth.register_user(
        db_conn,
        test_email,
        test_pwd,
        initial_profile={"height_cm": 182, "weight_kg": 80.5}
    )

    assert user_id > 0
    assert len(rec_key) > 30
    assert session.email == test_email
    assert len(session.dek) == 32
    assert session.encrypted_profile["height_cm"] == 182

    # Authenticate with correct password
    login_session = auth.authenticate_user(db_conn, test_email, test_pwd)
    assert login_session.user_id == user_id
    assert login_session.dek == session.dek
    assert login_session.encrypted_profile["weight_kg"] == 80.5

    # Authenticate with wrong password should fail
    with pytest.raises(ValueError, match="Fel e-postadress eller lösenord"):
        auth.authenticate_user(db_conn, test_email, "WrongPassword999!")

    # Clean up
    auth.delete_user_account(db_conn, user_id)

def test_account_recovery_and_password_reset(db_conn):
    test_email = "test_recovery_user@andrix.se"
    initial_pwd = "InitialPassword123!"
    new_pwd = "RecoveredPassword456!"

    with db_conn.cursor() as cur:
        cur.execute("DELETE FROM users WHERE email = %s", (test_email,))
        db_conn.commit()

    user_id, rec_key, session = auth.register_user(db_conn, test_email, initial_pwd)
    original_dek = session.dek

    # Recover account with valid recovery key
    new_rec_key, rec_session = auth.recover_account(db_conn, test_email, rec_key, new_pwd)
    assert rec_session.user_id == user_id
    assert rec_session.dek == original_dek
    assert new_rec_key != rec_key  # Old key was invalidated

    # Old password no longer works
    with pytest.raises(ValueError):
        auth.authenticate_user(db_conn, test_email, initial_pwd)

    # New password works
    new_session = auth.authenticate_user(db_conn, test_email, new_pwd)
    assert new_session.dek == original_dek

    # Old recovery key no longer works
    with pytest.raises(ValueError):
        auth.recover_account(db_conn, test_email, rec_key, "AnotherPassword789!")

    auth.delete_user_account(db_conn, user_id)

def test_change_password(db_conn):
    test_email = "test_change_pwd@andrix.se"
    old_pwd = "OldPassword123!"
    new_pwd = "BrandNewPassword123!"

    with db_conn.cursor() as cur:
        cur.execute("DELETE FROM users WHERE email = %s", (test_email,))
        db_conn.commit()

    user_id, rec_key, session = auth.register_user(db_conn, test_email, old_pwd)
    original_dek = session.dek

    # Change password
    success = auth.change_user_password(db_conn, user_id, old_pwd, new_pwd)
    assert success is True

    # Login with new password
    login_session = auth.authenticate_user(db_conn, test_email, new_pwd)
    assert login_session.dek == original_dek

    auth.delete_user_account(db_conn, user_id)
