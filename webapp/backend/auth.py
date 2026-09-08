"""User accounts and server-side sessions.

The desktop build had a single implicit user: whoever was logged into Windows.
The web build needs real accounts, so this module owns a small SQLite user store
plus opaque session tokens kept in an HTTP-only cookie.

Passwords are hashed with PBKDF2-HMAC-SHA256 from the standard library, so the
deployment needs no extra crypto dependency.
"""

import hashlib
import logging
import secrets
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

from . import config

logger = logging.getLogger(__name__)

PBKDF2_ROUNDS = 240_000
MIN_PASSWORD_LENGTH = 8


class AuthError(Exception):
    """Raised when registration or login cannot be completed."""


def _connect() -> sqlite3.Connection:
    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(config.USERS_DB)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_db() -> None:
    """Create the account tables if they do not exist yet."""
    with _connect() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                email TEXT UNIQUE NOT NULL,
                display_name TEXT,
                password_hash TEXT NOT NULL,
                created_at TEXT NOT NULL,
                last_login_at TEXT
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS sessions (
                token TEXT PRIMARY KEY,
                user_id INTEGER NOT NULL,
                created_at TEXT NOT NULL,
                expires_at TEXT NOT NULL,
                FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE
            )
            """
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_sessions_user ON sessions (user_id)")


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, PBKDF2_ROUNDS)
    return f"pbkdf2_sha256${PBKDF2_ROUNDS}${salt.hex()}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        algorithm, rounds, salt_hex, digest_hex = stored.split("$")
        if algorithm != "pbkdf2_sha256":
            return False
        digest = hashlib.pbkdf2_hmac(
            "sha256", password.encode("utf-8"), bytes.fromhex(salt_hex), int(rounds)
        )
        return secrets.compare_digest(digest.hex(), digest_hex)
    except (ValueError, TypeError):
        return False


def normalize_email(email: str) -> str:
    return (email or "").strip().lower()


def user_count() -> int:
    with _connect() as conn:
        return int(conn.execute("SELECT COUNT(*) AS c FROM users").fetchone()["c"])


def create_user(email: str, password: str, display_name: str = "") -> dict:
    email = normalize_email(email)
    if not email or "@" not in email:
        raise AuthError("Ange en giltig e-postadress.")
    if len(password or "") < MIN_PASSWORD_LENGTH:
        raise AuthError(f"Lösenordet måste vara minst {MIN_PASSWORD_LENGTH} tecken.")

    now = datetime.now().isoformat(timespec="seconds")
    try:
        with _connect() as conn:
            cursor = conn.execute(
                "INSERT INTO users (email, display_name, password_hash, created_at) VALUES (?, ?, ?, ?)",
                (email, (display_name or "").strip() or email.split("@")[0], hash_password(password), now),
            )
            user_id = int(cursor.lastrowid)
    except sqlite3.IntegrityError as exc:
        raise AuthError("Det finns redan ett konto med den e-postadressen.") from exc

    config.user_dir(user_id)  # Provision the per-user data directory eagerly.
    logger.info("Created account %s (id=%s)", email, user_id)
    return get_user(user_id)


def get_user(user_id: int) -> Optional[dict]:
    with _connect() as conn:
        row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
        return dict(row) if row else None


def get_user_by_email(email: str) -> Optional[dict]:
    with _connect() as conn:
        row = conn.execute("SELECT * FROM users WHERE email = ?", (normalize_email(email),)).fetchone()
        return dict(row) if row else None


def authenticate(email: str, password: str) -> dict:
    user = get_user_by_email(email)
    if not user or not verify_password(password, user["password_hash"]):
        raise AuthError("Fel e-postadress eller lösenord.")
    with _connect() as conn:
        conn.execute(
            "UPDATE users SET last_login_at = ? WHERE id = ?",
            (datetime.now().isoformat(timespec="seconds"), user["id"]),
        )
    return user


def change_password(user_id: int, current_password: str, new_password: str) -> None:
    user = get_user(user_id)
    if not user or not verify_password(current_password, user["password_hash"]):
        raise AuthError("Nuvarande lösenord stämmer inte.")
    if len(new_password or "") < MIN_PASSWORD_LENGTH:
        raise AuthError(f"Det nya lösenordet måste vara minst {MIN_PASSWORD_LENGTH} tecken.")
    with _connect() as conn:
        conn.execute(
            "UPDATE users SET password_hash = ? WHERE id = ?", (hash_password(new_password), user_id)
        )
        # Signing out every other device is the safe default after a password change.
        conn.execute("DELETE FROM sessions WHERE user_id = ?", (user_id,))


def create_session(user_id: int) -> str:
    token = secrets.token_urlsafe(32)
    now = datetime.now()
    with _connect() as conn:
        conn.execute(
            "INSERT INTO sessions (token, user_id, created_at, expires_at) VALUES (?, ?, ?, ?)",
            (
                token,
                user_id,
                now.isoformat(timespec="seconds"),
                (now + timedelta(days=config.SESSION_TTL_DAYS)).isoformat(timespec="seconds"),
            ),
        )
    return token


def resolve_session(token: Optional[str]) -> Optional[dict]:
    """Return the user behind a session token, or None if it is invalid/expired."""
    if not token:
        return None
    with _connect() as conn:
        row = conn.execute(
            """
            SELECT u.*, s.expires_at FROM sessions s
            JOIN users u ON u.id = s.user_id
            WHERE s.token = ?
            """,
            (token,),
        ).fetchone()
        if not row:
            return None
        if datetime.fromisoformat(row["expires_at"]) < datetime.now():
            conn.execute("DELETE FROM sessions WHERE token = ?", (token,))
            return None
    user = dict(row)
    user.pop("expires_at", None)
    return user


def destroy_session(token: Optional[str]) -> None:
    if not token:
        return
    with _connect() as conn:
        conn.execute("DELETE FROM sessions WHERE token = ?", (token,))


def delete_user(user_id: int) -> None:
    """Remove the account and every trace of its data from disk."""
    import shutil

    with _connect() as conn:
        conn.execute("DELETE FROM sessions WHERE user_id = ?", (user_id,))
        conn.execute("DELETE FROM users WHERE id = ?", (user_id,))
    path: Path = config.USER_DATA_DIR / str(user_id)
    if path.exists():
        shutil.rmtree(path, ignore_errors=True)
    logger.info("Deleted account id=%s and its data directory", user_id)
