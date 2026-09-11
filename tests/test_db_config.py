"""
Tests for DB configuration and env file loading behavior.
"""

import os
import pytest
from pathlib import Path
from unittest.mock import patch, mock_open

import garmin_db


def test_get_mariadb_connection_raises_when_no_password(monkeypatch):
    monkeypatch.delenv("MARIADB_PASSWORD", raising=False)
    with patch("garmin_db.load_db_env") as mock_load:
        with pytest.raises(RuntimeError, match="MARIADB_PASSWORD saknas"):
            garmin_db.get_mariadb_connection({"host": "localhost", "user": "test"})


def test_load_db_env_parses_key_values(tmp_path, monkeypatch):
    monkeypatch.delenv("MARIADB_PASSWORD", raising=False)
    env_file = tmp_path / ".env"
    env_file.write_text("MARIADB_PASSWORD=test_env_pass_123\nMARIADB_USER=testuser", encoding="utf-8")

    with patch("pathlib.Path.cwd", return_value=tmp_path), patch("pathlib.Path.home", return_value=tmp_path):
        garmin_db.load_db_env()

    assert os.environ.get("MARIADB_PASSWORD") == "test_env_pass_123"
    assert os.environ.get("MARIADB_USER") == "testuser"
