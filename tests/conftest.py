"""Shared pytest fixtures for the HealthChat test suite."""

from datetime import datetime, timedelta

import pytest

from garmin_db import GarminDatabase


@pytest.fixture
def db(tmp_path):
    """A fresh GarminDatabase backed by a throwaway SQLite file in a temp dir."""
    return GarminDatabase(db_path=tmp_path / "test_healthdata.db")


@pytest.fixture
def today_str():
    return datetime.now().strftime("%Y-%m-%d")


@pytest.fixture
def days_ago():
    """Return a helper that formats a date N days before today as YYYY-MM-DD."""
    def _fmt(n: int) -> str:
        return (datetime.now() - timedelta(days=n)).strftime("%Y-%m-%d")
    return _fmt
