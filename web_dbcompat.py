"""SQLite compatibility layer for the account tables.

``garmin_db`` falls back to SQLite when MariaDB is unreachable, but ``auth``
speaks pymysql: it uses ``%s`` placeholders and ``with conn.cursor() as cur``,
neither of which sqlite3 supports. Without this shim the whole application —
not just the health tables — is dead whenever the MariaDB host is down, and the
account tests can only ever skip.

This wraps a sqlite3 connection in the small slice of the pymysql API that
``auth`` actually uses, and creates the ``users`` table in SQLite's dialect so
the same registration and login code runs against either backend.
"""

import logging
import re
import sqlite3
from pathlib import Path
from typing import Any, Optional, Sequence

logger = logging.getLogger("web_dbcompat")

# The MariaDB users table from init_mariadb.sql, in SQLite's dialect. BLOB and
# TEXT hold the same bytes the MariaDB columns do.
USERS_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    email TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    kdf_salt BLOB NOT NULL,
    wrapped_dek BLOB NOT NULL,
    dek_nonce BLOB NOT NULL,
    recovery_wrapped_dek BLOB,
    recovery_salt BLOB,
    recovery_nonce BLOB,
    encrypted_profile BLOB,
    profile_nonce BLOB,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
)
"""

_PLACEHOLDER = re.compile(r"%s")


def _translate(sql: str) -> str:
    """pymysql placeholders and quoting to their SQLite equivalents."""
    return _PLACEHOLDER.sub("?", sql).replace("`", '"')


class _CursorContext:
    """A sqlite3 cursor that also works as a context manager."""

    def __init__(self, cursor: sqlite3.Cursor):
        self._cursor = cursor

    def __enter__(self) -> "_CursorContext":
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        self._cursor.close()
        return False

    def execute(self, sql: str, params: Sequence[Any] = ()) -> "_CursorContext":
        self._cursor.execute(_translate(sql), tuple(params))
        return self

    def executemany(self, sql: str, seq: Sequence[Sequence[Any]]) -> "_CursorContext":
        self._cursor.executemany(_translate(sql), [tuple(p) for p in seq])
        return self

    def fetchone(self):
        return self._cursor.fetchone()

    def fetchall(self):
        return self._cursor.fetchall()

    def close(self) -> None:
        self._cursor.close()

    @property
    def lastrowid(self):
        return self._cursor.lastrowid

    @property
    def rowcount(self):
        return self._cursor.rowcount

    @property
    def description(self):
        return self._cursor.description


class SqliteAuthConnection:
    """A sqlite3 connection wearing the parts of the pymysql API ``auth`` uses."""

    def __init__(self, connection: sqlite3.Connection):
        self._connection = connection
        self._connection.execute("PRAGMA journal_mode=WAL")
        self._connection.execute(USERS_TABLE_SQL)
        self._connection.commit()

    def cursor(self) -> _CursorContext:
        return _CursorContext(self._connection.cursor())

    def commit(self) -> None:
        self._connection.commit()

    def rollback(self) -> None:
        self._connection.rollback()

    def close(self) -> None:
        self._connection.close()

    @property
    def raw(self) -> sqlite3.Connection:
        return self._connection


def connect(db_path: Path) -> SqliteAuthConnection:
    """Open the account database stored beside the SQLite health data."""
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    return SqliteAuthConnection(sqlite3.connect(db_path))


def is_duplicate_error(exc: Exception) -> bool:
    """True when a failed insert was a unique-constraint violation."""
    return isinstance(exc, sqlite3.IntegrityError) and "UNIQUE" in str(exc).upper()
