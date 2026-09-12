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
