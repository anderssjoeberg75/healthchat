import pytest
from unittest.mock import MagicMock
import tkinter as tk

from charts_view import HealthChartsView


@pytest.fixture
def mock_db():
    db = MagicMock()
    db.get_daily_summary_history.return_value = []
    db.get_sleep_history.return_value = []
    db.get_body_battery_history.return_value = []
    db.get_stress_history.return_value = []
    db.get_hrv_history.return_value = []
    db.get_activities_history.return_value = []
    db.get_latest_body_composition.return_value = None
    db.get_body_composition_history.return_value = []
    db.get_calorie_burn_history.return_value = []
    return db


def test_charts_view_tabs_creation_and_switching(mock_db):
    try:
        root = tk.Tk()
    except Exception:
        pytest.skip("Tkinter display not available")

    colors = {'accent': '#0078D4'}
    view = HealthChartsView(root, mock_db, colors)

    # Initial active tab should be "health" on app start
    assert view.active_tab == "health"

    # Check tab buttons exist
    assert hasattr(view, 'tab_health_btn')
    assert hasattr(view, 'tab_training_btn')

    assert view.tab_health_btn.cget('text') == "❤️ Hälsa"
    assert view.tab_training_btn.cget('text') == "🏃 Träning"

    # Test tab switching to training
    view.switch_tab("training")
    assert view.active_tab == "training"

    # Test tab switching back to health
    view.switch_tab("health")
    assert view.active_tab == "health"

    # Test backward compatibility switch to dashboard / evolab (points to health)
    view.switch_tab("dashboard")
    assert view.active_tab == "health"

    view.switch_tab("evolab")
    assert view.active_tab == "health"

    root.destroy()


def test_get_recovery_ai_recommendation(mock_db):
    try:
        root = tk.Tk()
    except Exception:
        pytest.skip("Tkinter display not available")

    colors = {'accent': '#0078D4'}
    view = HealthChartsView(root, mock_db, colors)

    import hr_zones_calc
    calc = hr_zones_calc.calculate_hr_zones(age=40, resting_hr=60)

    # Test 57% recovery score (Moderate recovery tier)
    rec_text = view.get_recovery_ai_recommendation(57, calc)
    lines = rec_text.splitlines()
    assert len(lines) == 5
    assert "Återhämtning 57%" in lines[0]
    assert "Pulsnivå:" in lines[2]
    assert "Zon 1–2" in lines[2]

    # Test 85% recovery score (High recovery tier)
    rec_high = view.get_recovery_ai_recommendation(85, calc)
    lines_high = rec_high.splitlines()
    assert len(lines_high) == 5
    assert "Återhämtning 85%" in lines_high[0]
    assert "Zon 3–4" in lines_high[2]

    root.destroy()


def test_max_hr_selection_ignores_recorded_activities(mock_db):
    try:
        root = tk.Tk()
    except Exception:
        pytest.skip("Tkinter display not available")

    # Setup mock_db with activity history having max_hr = 210, which should BE IGNORED
    mock_db.get_max_recorded_hr.return_value = 210
    mock_db.get_metadata.return_value = None

    colors = {'accent': '#0078D4'}
    view = HealthChartsView(root, mock_db, colors)

    # 1. Profile with user max_hr = 175
    profile_with_user_max = {'age': 40, 'max_hr': 175}
    # Render HR zones tab or check logic: user_max_hr should take precedence
    # 2. Profile without user max_hr, but garmin metadata exists = 182
    mock_db.get_metadata.side_effect = lambda k: "182" if k == "garmin_max_hr" else None
    profile_empty = {'age': 40, 'max_hr': 0}

    # Verify that get_max_recorded_hr is never called when rendering HR zones
    # We test _build_hr_zones_tab doesn't use 210
    view.db = mock_db
    view.profile = profile_with_user_max
    view.hr_zones_card_body = tk.Frame(root)

    view.update_hr_zones_card()

    assert mock_db.get_max_recorded_hr.call_count == 0

    root.destroy()


