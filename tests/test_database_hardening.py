"""
Tests for Database Layer Hardening (Omgång 4):
- TLS-3 (kod): SSL/TLS support and hostname validation in get_mariadb_connection and pool.
- PF-7: Module-global shared connection pool and single SQLite DDL execution.
- S-14: require_mariadb prevents silent SQLite fallback and returns 503 on failure.
"""

import os
import pytest
from unittest.mock import patch, MagicMock
from pathlib import Path

import garmin_db
from garmin_db import GarminDatabase, get_mariadb_connection, get_shared_mariadb_pool, reset_sqlite_init_cache
from fastapi.testclient import TestClient
from server import app


def test_tls_3_get_mariadb_connection_raises_when_require_tls_missing_ca(monkeypatch, tmp_path):
    """TLS-3: If MARIADB_REQUIRE_TLS=1 and CA file does not exist, get_mariadb_connection must raise."""
    monkeypatch.setenv("MARIADB_REQUIRE_TLS", "1")
    monkeypatch.setenv("MARIADB_SSL_CA", str(tmp_path / "non_existent_ca.pem"))
    monkeypatch.setenv("MARIADB_PASSWORD", "some_pass")

    with pytest.raises(RuntimeError, match="MARIADB_REQUIRE_TLS=1 men SSL CA certifikat saknas"):
        get_mariadb_connection({"host": "localhost"})


def test_tls_3_get_mariadb_connection_configures_ssl_when_ca_exists(monkeypatch, tmp_path):
    """TLS-3: When CA file exists, ssl config dictionary with check_hostname is passed to pymysql.connect."""
    ca_file = tmp_path / "ca.pem"
    ca_file.write_text("dummy ca content", encoding="utf-8")
    monkeypatch.setenv("MARIADB_SSL_CA", str(ca_file))
    monkeypatch.setenv("MARIADB_PASSWORD", "test_pass")

    with patch("pymysql.connect") as mock_connect:
        mock_connect.return_value = MagicMock()
        get_mariadb_connection({"host": "db.example.internal", "user": "healthchat"})
        mock_connect.assert_called_once()
        _, kwargs = mock_connect.call_args
        assert kwargs.get("ssl") is not None
        assert kwargs["ssl"].get("ca") == str(ca_file)
        assert kwargs["ssl"].get("check_hostname") is True


def test_pf_7_multiple_instances_share_same_pool(monkeypatch):
    """PF-7: Multiple GarminDatabase instances share the same singleton pool instance."""
    db1 = GarminDatabase()
    db2 = GarminDatabase()

    if db1.is_mariadb and db2.is_mariadb:
        assert db1.pool is not None
        assert db1.pool is db2.pool, "GarminDatabase instances must share the same PooledDB pool"


def test_pf_7_init_sqlite_db_runs_at_most_once_per_path(tmp_path):
    """PF-7: Multiple instantiations with the same db_path only run SQLite table init once."""
    reset_sqlite_init_cache()
    db_file = tmp_path / "shared_perf_test.db"

    assert garmin_db._SQLITE_INIT_CALL_COUNT == 0
    db1 = GarminDatabase(db_path=db_file)
    assert garmin_db._SQLITE_INIT_CALL_COUNT == 1

    db2 = GarminDatabase(db_path=db_file)
    db3 = GarminDatabase(db_path=db_file)
    assert garmin_db._SQLITE_INIT_CALL_COUNT == 1, "init_sqlite_db must not re-run for an already initialized db"


def test_s_14_require_mariadb_raises_and_prevents_sqlite_fallback(monkeypatch):
    """S-14: When require_mariadb=True and MariaDB is unreachable, must raise RuntimeError without falling back to SQLite."""
    bad_config = {
        "host": "unreachable.invalid.host.test",
        "port": 3306,
        "user": "fake_user",
        "password": "fake_password",
        "database": "healthchat"
    }

    with pytest.raises(RuntimeError, match="MariaDB-anslutning krävs"):
        GarminDatabase(mariadb_config=bad_config, require_mariadb=True)


def test_s_14_server_error_handler_returns_503_on_mariadb_failure(monkeypatch):
    """S-14: If an endpoint encounters a MariaDB connection failure, server returns 503 instead of 500 or shared SQLite."""
    client = TestClient(app, base_url="https://testserver")

    with patch("server.get_db") as mock_get_db:
        mock_get_db.side_effect = RuntimeError("MariaDB-anslutning krävs i fleranvändarläge, men misslyckades: connection refused")
        res = client.post("/api/auth/login", json={"email": "any@user.se", "password": "pwd"})
        assert res.status_code == 503
        assert "Databasen är inte tillgänglig" in res.json().get("detail", "")
