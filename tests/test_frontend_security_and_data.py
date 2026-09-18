"""
Tests for Frontend UI-1 & UI-2:
- UI-1: Verify absence of fake mock values (generateMockSeries, 98.3, 21.4, 72.1, 1195).
- UI-2: Verify XSS escaping (escapeHtml) on dynamic activity/zone data in tables.
"""

from pathlib import Path
import re

APP_JS_PATH = Path(__file__).resolve().parent.parent / "static" / "app.js"


def test_ui_1_no_mock_series_or_fake_health_values():
    assert APP_JS_PATH.exists(), f"static/app.js not found at {APP_JS_PATH}"
    content = APP_JS_PATH.read_text(encoding="utf-8")

    # generateMockSeries must not exist
    assert "generateMockSeries" not in content, "Found generateMockSeries in static/app.js"

    # Hardcoded fake mock values must not exist
    assert "98.3" not in content, "Found fake weight 98.3 in static/app.js"
    assert "21.4" not in content, "Found fake body fat 21.4 in static/app.js"
    assert "72.1" not in content, "Found fake muscle mass 72.1 in static/app.js"
    assert "1195" not in content, "Found fake calorie burn 1195 in static/app.js"


def test_ui_2_escape_html_present_and_applied_to_activity_tables():
    content = APP_JS_PATH.read_text(encoding="utf-8")

    # escapeHtml helper must be defined
    assert "function escapeHtml(str)" in content, "escapeHtml function definition missing"

    # Must escape activity fields in renderActivitiesTable
    assert re.search(r"escapeHtml\(\s*act\.activity_name", content), "act.activity_name must be escaped"
    assert re.search(r"escapeHtml\(\s*act\.source", content), "act.source must be escaped"
    assert re.search(r"escapeHtml\(\s*act\.date", content), "act.date must be escaped"

    # Must escape zone table fields
    assert "escapeHtml(z.name" in content or "escapeHtml(z.title" in content, "Heart zone fields must be escaped"


def test_profile_page_hr_zones_and_maf_table_under_bmi():
    index_path = Path(__file__).resolve().parent.parent / "static" / "index.html"
    assert index_path.exists(), f"static/index.html not found at {index_path}"
    html = index_path.read_text(encoding="utf-8")

    # Verify elements exist on profile page
    assert 'id="prof-bone"' in html, "prof-bone must be in index.html"
    assert 'id="prof-water"' in html, "prof-water must be in index.html"
    assert 'id="prof-waist"' in html, "prof-waist must be in index.html"
    assert 'id="prof-bmi"' in html, "prof-bmi must be in index.html"
    assert 'id="prof-hr-zones-header-info"' in html, "prof-hr-zones-header-info must be in index.html"
    assert 'id="prof-hr-zones-table-body"' in html, "prof-hr-zones-table-body must be in index.html"
    assert 'id="prof-maf-title"' in html, "prof-maf-title must be in index.html"
    assert 'id="prof-maf-info"' in html, "prof-maf-info must be in index.html"

    # Verify placement: waist is under bone/water and before/at BMI row, and HR zones table is placed after prof-bmi row and before prof-training-goals
    water_pos = html.find('id="prof-water"')
    waist_pos = html.find('id="prof-waist"')
    bmi_pos = html.find('id="prof-bmi"')
    zones_pos = html.find('id="prof-hr-zones-table-body"')
    goals_pos = html.find('id="prof-training-goals"')

    assert water_pos != -1 and waist_pos != -1 and bmi_pos != -1 and zones_pos != -1 and goals_pos != -1
    assert water_pos < waist_pos <= bmi_pos < zones_pos < goals_pos, (
        "Midjemått must be under skelettmassa/kroppsvatten and before HR zones"
    )

