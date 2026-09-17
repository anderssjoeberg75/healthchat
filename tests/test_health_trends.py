"""Tester för health_trends - återhämtningstrender till COACH AI:s sammanhang.

Tyngdpunkten ligger på de fall där en naiv implementation ger fel svar:
nollor som egentligen betyder "saknas", för tunt underlag, och att riktningen
"dålig" skiljer sig mellan vilopuls och HRV.
"""

from datetime import date, timedelta

import pytest

import health_trends as ht


TODAY = date(2026, 9, 17)


def series(values_by_offset, key, start=TODAY):
    """Bygg historikrader: {dagar_bakåt: värde} -> [{"date": ..., key: ...}]."""
    return [
        {"date": (start - timedelta(days=offset)).isoformat(), key: value}
        for offset, value in sorted(values_by_offset.items())
    ]


def flat(recent, baseline, key, start=TODAY):
    """7 dagar med `recent`, därefter 14 dagar med `baseline`."""
    rows = {i: (recent if i < ht.RECENT_DAYS else baseline) for i in range(21)}
    return series(rows, key, start)


# --- Fönster och riktning ---------------------------------------------------

def test_rising_resting_hr_is_a_warning():
    """Vilopuls upp 7,4 % passerar +5 %-tröskeln."""
    t = ht.compute_trend(flat(58, 54, "resting_hr"), "resting_hr",
                         higher_is_better=False, warn_pct=5.0, today=TODAY)
    assert t["status"] == "warn"
    assert t["pct_change"] == pytest.approx(7.4, abs=0.1)
    assert t["n_recent"] == 7 and t["n_baseline"] == 14


def test_falling_resting_hr_is_an_improvement():
    """Samma metrik åt andra hållet ska inte larma."""
    t = ht.compute_trend(flat(51, 55, "resting_hr"), "resting_hr",
                         higher_is_better=False, warn_pct=5.0, today=TODAY)
    assert t["status"] == "improved"


def test_falling_hrv_is_a_warning():
    """HRV är omvänd mot vilopuls: nedgång är det oroande."""
    t = ht.compute_trend(flat(44, 51, "last_night_avg"), "last_night_avg",
                         higher_is_better=True, warn_pct=10.0, today=TODAY)
    assert t["status"] == "warn"
    assert t["pct_change"] == pytest.approx(-13.7, abs=0.1)


def test_rising_hrv_is_an_improvement():
    t = ht.compute_trend(flat(56, 48, "last_night_avg"), "last_night_avg",
                         higher_is_better=True, warn_pct=10.0, today=TODAY)
    assert t["status"] == "improved"


def test_small_change_is_normal_variation():
    t = ht.compute_trend(flat(55, 54, "resting_hr"), "resting_hr",
                         higher_is_better=False, warn_pct=5.0, today=TODAY)
    assert t["status"] == "ok"


def test_threshold_boundary_counts_as_warning():
    """Exakt på tröskeln ska larma - prompten säger '+5 % eller mer'."""
    t = ht.compute_trend(flat(105, 100, "resting_hr"), "resting_hr",
                         higher_is_better=False, warn_pct=5.0, today=TODAY)
    assert t["pct_change"] == pytest.approx(5.0, abs=0.01)
    assert t["status"] == "warn"


# --- Datafällor -------------------------------------------------------------

def test_zero_resting_hr_is_treated_as_missing():
    """upsert_daily_summary skriver resting_hr=0 när Garmin inte gav något värde.

    Räknas nollan som ett mätvärde dras snittet ned och trenden blir påhittad.
    """
    rows = flat(0, 54, "resting_hr")
    t = ht.compute_trend(rows, "resting_hr", higher_is_better=False,
                         warn_pct=5.0, today=TODAY)
    assert t["n_recent"] == 0
    assert t["status"] == "insufficient"


def test_all_zeros_yields_no_data():
    rows = flat(0, 0, "resting_hr")
    t = ht.compute_trend(rows, "resting_hr", higher_is_better=False,
                         warn_pct=5.0, today=TODAY)
    assert t["status"] == "no_data"
    assert ht.build_trend_lines(daily_summary=rows, today=TODAY) == []


def test_too_few_days_reports_insufficient_not_a_percentage():
    """Två mätpunkter är brus, inte en trend."""
    rows = series({0: 58, 1: 57, 10: 54, 11: 54}, "resting_hr")
    t = ht.compute_trend(rows, "resting_hr", higher_is_better=False,
                         warn_pct=5.0, today=TODAY)
    assert t["status"] == "insufficient"
    assert t["pct_change"] is None


def test_unparseable_dates_are_skipped_not_fatal():
    rows = flat(58, 54, "resting_hr")
    rows.append({"date": "inte-ett-datum", "resting_hr": 999})
    rows.append({"date": None, "resting_hr": 999})
    t = ht.compute_trend(rows, "resting_hr", higher_is_better=False,
                         warn_pct=5.0, today=TODAY)
    assert t["status"] == "warn"
    assert t["n_recent"] == 7


def test_data_outside_both_windows_is_ignored():
    """Dagar äldre än baslinjefönstret ska inte påverka snittet."""
    rows = flat(58, 54, "resting_hr")
    rows += series({60: 90, 90: 95}, "resting_hr")
    t = ht.compute_trend(rows, "resting_hr", higher_is_better=False,
                         warn_pct=5.0, today=TODAY)
    assert t["n_baseline"] == 14
    assert t["baseline_avg"] == pytest.approx(54.0)


def test_empty_and_malformed_input_is_safe():
    for rows in (None, [], [None], ["inte en dict"], [{}]):
        t = ht.compute_trend(rows, "resting_hr", higher_is_better=False,
                             warn_pct=5.0, today=TODAY)
        assert t["status"] == "no_data"


def test_latest_value_is_the_most_recent_day():
    rows = series({0: 58, 3: 61, 6: 55}, "resting_hr")
    t = ht.compute_trend(rows, "resting_hr", higher_is_better=False,
                         warn_pct=5.0, today=TODAY)
    assert t["latest"] == 58.0
    assert t["latest_date"] == TODAY.isoformat()


# --- Formaterade rader ------------------------------------------------------

def test_build_trend_lines_covers_all_three_metrics():
    lines = ht.build_trend_lines(
        daily_summary=flat(58, 54, "resting_hr"),
        hrv=flat(44, 51, "last_night_avg"),
        sleep=flat(6.2, 7.3, "total_sleep_hours"),
        today=TODAY,
    )
    assert len(lines) == 3
    assert lines[0].startswith("Vilopuls:")
    assert lines[1].startswith("HRV:")
    assert lines[2].startswith("Sömn:")
    assert all("⚠️" in line for line in lines), "alla tre avviker ogynnsamt och ska flaggas"


def test_lines_use_swedish_decimal_comma():
    lines = ht.build_trend_lines(hrv=flat(44, 51, "last_night_avg"), today=TODAY)
    assert "-13,7 %" in lines[0]
    assert "13.7" not in lines[0]


def test_insufficient_line_tells_the_model_not_to_conclude():
    lines = ht.build_trend_lines(
        daily_summary=series({0: 58, 1: 57}, "resting_hr"), today=TODAY
    )
    assert len(lines) == 1
    assert "Otillräckligt underlag" in lines[0]
    assert "dra inga slutsatser" in lines[0]
    assert "%" not in lines[0], "ett procenttal utan underlag är vilseledande"


def test_no_sources_gives_no_lines():
    assert ht.build_trend_lines(today=TODAY) == []


def test_history_days_needed_covers_both_windows():
    assert ht.history_days_needed() == ht.RECENT_DAYS + ht.BASELINE_DAYS == 21
