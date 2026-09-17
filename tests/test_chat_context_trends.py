"""Verifierar att återhämtningstrenderna når hela vägen ut i AI-sammanhanget.

Testet går genom den riktiga /api/ai/chat-endpointen och fångar den `garmin_context`
som skickas till AIClient. Enhetstesterna i test_health_trends.py täcker beräkningen;
det här testet täcker kopplingen - att rätt antal dagar hämtas ur databasen och att
raderna hamnar i sammanhanget.
"""

from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient

import health_trends
import server
from auth import UserSession

TODAY = date.today()


def _days(recent, baseline, key):
    """21 dagars historik: 7 dagar med `recent`, 14 med `baseline`. Stigande datum."""
    rows = []
    for offset in range(20, -1, -1):
        value = recent if offset < health_trends.RECENT_DAYS else baseline
        rows.append({"date": (TODAY - timedelta(days=offset)).isoformat(), key: value})
    return rows


class FakeDB:
    """Minimal GarminDatabase-ersättare som registrerar vilka dagsintervall som begärs."""

    def __init__(self):
        self.requested = {}

    def _record(self, name, days):
        self.requested[name] = days

    def get_activities_history(self, days):
        self._record("activities", days)
        return []

    def get_sleep_history(self, days):
        self._record("sleep", days)
        return _days(6.2, 7.3, "total_sleep_hours")

    def get_hrv_history(self, days):
        self._record("hrv", days)
        return _days(44, 51, "last_night_avg")

    def get_daily_summary_history(self, days):
        self._record("daily_summary", days)
        return _days(58, 54, "resting_hr")

    def get_latest_body_composition(self):
        return {}


@pytest.fixture
def captured(monkeypatch):
    """Kör ett chattanrop och returnera (garmin_context, FakeDB)."""
    fake_db = FakeDB()
    box = {}

    monkeypatch.setattr(server, "bind_user_db", lambda session: fake_db)

    class StubClient:
        conversation_history = []

        def __init__(self, *a, **kw):
            pass

        def chat_stream(self, message, garmin_context=None):
            box["context"] = garmin_context
            yield "ok"

    monkeypatch.setattr(server, "AIClient", StubClient)

    session = UserSession(
        user_id=1,
        email="trend@example.com",
        dek=bytearray(32),
        encrypted_profile={"age": 44},
    )
    server.app.dependency_overrides[server.get_current_session] = lambda: session
    try:
        # TestClient konstrueras utan context manager: `with` skulle trigga
        # startup_db_check, som kräver en levande MariaDB (se Q-11 i board.md).
        client = TestClient(server.app, base_url="https://testserver")
        res = client.post("/api/ai/chat", json={"message": "Hur mår jag idag?"})
        assert res.status_code == 200, res.text
        res.read()
    finally:
        server.app.dependency_overrides.pop(server.get_current_session, None)

    assert "context" in box, "chat_stream anropades aldrig"
    return box["context"], fake_db


def test_enough_history_is_fetched_for_both_windows(captured):
    """Trendfönstren kräver 21 dagar - hämtas färre blir baslinjen tom."""
    _, fake_db = captured
    needed = health_trends.history_days_needed()
    assert fake_db.requested["sleep"] == needed
    assert fake_db.requested["hrv"] == needed
    assert fake_db.requested["daily_summary"] == needed


def test_trend_section_is_present_in_context(captured):
    context, _ = captured
    assert "ÅTERHÄMTNINGSTRENDER" in context
    assert "senaste 7 dagarna mot de 14 närmast före" in context


def test_all_three_metrics_reach_the_model(captured):
    context, _ = captured
    assert "Vilopuls:" in context
    assert "HRV:" in context
    assert "Sömn:" in context


def test_baseline_and_percentage_are_included(captured):
    """Det är jämförelsen mot baslinjen som gör värdet tolkbart för modellen."""
    context, _ = captured
    assert "baslinje" in context
    assert "-13,7 %" in context, "HRV-nedgången ska redovisas i procent"
    assert "⚠️" in context, "avvikelser över tröskeln ska flaggas"


def test_single_night_values_are_still_present(captured):
    """Trenderna ersätter inte nattvärdena - de kompletterar dem."""
    context, _ = captured
    assert "Senaste HRV:" in context
    assert "Senaste sömn:" in context
