"""Encrypted per-user key/value store for the web application.

The desktop build kept settings, saved prompts, quick questions and chat
history in files under ``~/.healthchat`` on the user's own machine. On a shared
server that state has to be per account *and* protected the same way health
data is, so it is stored in the existing ``sync_metadata`` table (which is
already keyed by ``user_id``) as an AES-256-GCM payload encrypted with the
user's DEK.

Values are plain JSON structures. When no DEK is available — the SQLite
fallback used by the desktop build and by tests — they are stored as readable
JSON instead, so the same code works in both modes.
"""

import base64
import json
import logging
from typing import Any, Optional

import crypto

logger = logging.getLogger("web_store")

# Marker prefixes so a stored value describes its own format.
_ENCRYPTED_PREFIX = "enc:v1:"
_PLAIN_PREFIX = "json:v1:"


def _dek_of(session) -> Optional[bytes]:
    dek = getattr(session, "dek", None) if session is not None else None
    return bytes(dek) if dek else None


def encode(session, value: Any) -> str:
    """Serialise ``value`` for storage, encrypting it when a DEK is available."""
    dek = _dek_of(session)
    if not dek:
        return _PLAIN_PREFIX + json.dumps(value, ensure_ascii=False, default=str)

    nonce, ciphertext = crypto.encrypt_payload(dek, value)
    return _ENCRYPTED_PREFIX + json.dumps(
        {
            "n": base64.b64encode(nonce).decode("ascii"),
            "c": base64.b64encode(ciphertext).decode("ascii"),
        }
    )


def decode(session, raw: Optional[str], default: Any = None) -> Any:
    """Read back a value written by :func:`encode`."""
    if not raw:
        return default

    if raw.startswith(_PLAIN_PREFIX):
        try:
            return json.loads(raw[len(_PLAIN_PREFIX):])
        except ValueError:
            logger.warning("Discarding unreadable plain value")
            return default

    if raw.startswith(_ENCRYPTED_PREFIX):
        dek = _dek_of(session)
        if not dek:
            # Encrypted with a key this session does not hold.
            return default
        try:
            envelope = json.loads(raw[len(_ENCRYPTED_PREFIX):])
            return crypto.decrypt_payload(
                dek,
                base64.b64decode(envelope["c"]),
                base64.b64decode(envelope["n"]),
            )
        except Exception as exc:
            logger.warning("Could not decrypt stored value: %s", exc)
            return default

    # Anything else predates the markers; try plain JSON, else hand back the text.
    try:
        return json.loads(raw)
    except ValueError:
        return raw


_WIDENED: set = set()


def ensure_capacity(db) -> None:
    """Widen ``sync_metadata.value`` to LONGTEXT on an existing MariaDB.

    The table was created with ``TEXT`` (64 KB). It now also holds this store's
    encrypted payloads, and a long conversation passes that limit — MariaDB then
    truncates or rejects the write, losing the chat. Widening is safe and
    idempotent; the app may lack ALTER rights, in which case this logs the
    statement to run by hand instead of failing the request.
    """
    if not getattr(db, "is_mariadb", False) or not getattr(db, "pool", None):
        return  # SQLite has no such limit
    key = id(db)
    if key in _WIDENED:
        return
    _WIDENED.add(key)

    try:
        conn = db.get_mariadb_conn()
    except Exception as exc:
        logger.debug("Could not check sync_metadata capacity: %s", exc)
        return

    current = "TEXT"
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT DATA_TYPE FROM information_schema.COLUMNS "
                "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'sync_metadata' "
                "AND COLUMN_NAME = 'value'"
            )
            row = cur.fetchone()
            current = (row[0] if row else "").lower()
            if not current or current == "longtext":
                return

            cur.execute("ALTER TABLE sync_metadata MODIFY `value` LONGTEXT")
            logger.info("Widened sync_metadata.value from %s to LONGTEXT", current)
    except Exception as exc:
        logger.warning(
            "sync_metadata.value is still %s and long chats will not fit. "
            "Run this once as a user with ALTER rights: "
            "ALTER TABLE sync_metadata MODIFY `value` LONGTEXT;  (%s)",
            current,
            exc,
        )
    finally:
        try:
            conn.close()
        except Exception:
            pass


def read(db, session, key: str, default: Any = None) -> Any:
    """Load one stored value for the session's user."""
    try:
        return decode(session, db.get_metadata(key), default)
    except Exception as exc:
        logger.error("Could not read %s: %s", key, exc)
        return default


def write(db, session, key: str, value: Any) -> None:
    """Store one value for the session's user."""
    ensure_capacity(db)
    db.set_metadata(key, encode(session, value))
