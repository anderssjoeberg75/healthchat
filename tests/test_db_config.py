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
    monkeypatch.delenv("MARIADB_USER", raising=False)
    env_file = tmp_path / ".env"
    env_file.write_text("MARIADB_PASSWORD=test_env_pass_123\nMARIADB_USER=testuser", encoding="utf-8")

    with patch("pathlib.Path.cwd", return_value=tmp_path), patch("pathlib.Path.home", return_value=tmp_path):
        garmin_db.load_db_env()

    assert os.environ.get("MARIADB_PASSWORD") == "test_env_pass_123"
    assert os.environ.get("MARIADB_USER") == "testuser"


def test_load_db_env_does_not_override_existing_environment(tmp_path, monkeypatch):
    """En fil i hemkatalogen får inte skriva över det driftmiljön redan satt."""
    monkeypatch.setenv("MARIADB_PASSWORD", "from_systemd_environmentfile")
    env_file = tmp_path / ".env"
    env_file.write_text("MARIADB_PASSWORD=from_stray_home_file\n", encoding="utf-8")

    with patch("pathlib.Path.cwd", return_value=tmp_path), patch("pathlib.Path.home", return_value=tmp_path):
        garmin_db.load_db_env()

    assert os.environ["MARIADB_PASSWORD"] == "from_systemd_environmentfile"


def test_auto_created_db_env_has_no_credentials_and_is_private(tmp_path, monkeypatch):
    """Mallen som skapas automatiskt ska vara tom på värden och bara läsbar av ägaren."""
    monkeypatch.delenv("MARIADB_PASSWORD", raising=False)
    monkeypatch.delenv("MARIADB_USER", raising=False)
    home = tmp_path / "home"
    cwd = tmp_path / "cwd"
    home.mkdir()
    cwd.mkdir()

    with patch("pathlib.Path.cwd", return_value=cwd), patch("pathlib.Path.home", return_value=home):
        garmin_db.load_db_env()

    created = home / ".healthchat" / "db.env"
    assert created.is_file(), "db.env-mallen skapades inte"
    if os.name != "nt":
        assert created.stat().st_mode & 0o777 == 0o600, "mallen är läsbar för andra"

    for line in created.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        assert not stripped or stripped.startswith("#"), f"mallen sätter ett värde: {stripped!r}"

    # Mallen får inte ha smugit in några miljövariabler.
    assert os.environ.get("MARIADB_PASSWORD") is None
    assert os.environ.get("MARIADB_USER") is None


def test_empty_values_in_env_file_are_ignored(tmp_path, monkeypatch):
    """`MARIADB_PASSWORD=` ska inte ge en tom sträng som ser ut som ett lösenord."""
    monkeypatch.delenv("MARIADB_PASSWORD", raising=False)
    env_file = tmp_path / ".env"
    env_file.write_text("MARIADB_PASSWORD=\nMARIADB_DB=healthchat\n", encoding="utf-8")

    with patch("pathlib.Path.cwd", return_value=tmp_path), patch("pathlib.Path.home", return_value=tmp_path):
        garmin_db.load_db_env()

    assert os.environ.get("MARIADB_PASSWORD") is None
    assert os.environ.get("MARIADB_DB") == "healthchat"
