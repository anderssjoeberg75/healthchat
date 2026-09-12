"""Tests for withings_handler.WithingsDataHandler."""

from unittest.mock import MagicMock, patch
import pytest
from withings_handler import WithingsDataHandler
from garmin_db import GarminDatabase


def test_parse_measurements_converts_scaling_and_types():
    raw_measuregrps = [
        {
            "date": 1771495200,  # 2026-02-19
            "measures": [
                {"type": 1, "value": 754, "unit": -1},    # 75.4 kg
                {"type": 6, "value": 162, "unit": -1},    # 16.2 % fat
                {"type": 76, "value": 581, "unit": -1},   # 58.1 kg muscle
                {"type": 88, "value": 32, "unit": -1},    # 3.2 kg bone
                {"type": 77, "value": 555, "unit": -1},   # 55.5 % water
            ]
        }
    ]

    parsed = WithingsDataHandler.parse_measurements(raw_measuregrps)
    assert len(parsed) == 1
    record = parsed[0]

    assert record["weight_kg"] == 75.4
    assert record["fat_ratio_pct"] == 16.2
    assert record["muscle_mass_kg"] == 58.1
    assert record["bone_mass_kg"] == 3.2
    assert record["water_pct"] == 55.5
    assert record["source"] == "withings"


def test_upsert_and_query_body_composition(db):
    db.upsert_body_composition(
        date="2026-08-19",
        weight_kg=78.5,
        fat_ratio_pct=17.5,
        muscle_mass_kg=60.0,
        bone_mass_kg=3.5,
        water_pct=54.0,
        source="withings"
    )

    latest = db.get_latest_body_composition()
    assert latest is not None
    assert latest["date"] == "2026-08-19"
    assert latest["weight_kg"] == 78.5
    assert latest["fat_ratio_pct"] == 17.5
    assert latest["muscle_mass_kg"] == 60.0
    assert latest["source"] == "withings"


def test_sync_withings_data_saves_to_db(tmp_path):
    test_db = GarminDatabase(db_path=tmp_path / "withings_test.db")
    handler = WithingsDataHandler(
        client_id="dummy_id",
        client_secret="dummy_secret",
        refresh_token="dummy_refresh",
        access_token="dummy_access",
        db=test_db
    )

    mock_records = [
        {
            "date": "2026-08-19",
            "weight_kg": 80.2,
            "fat_ratio_pct": 18.0,
            "muscle_mass_kg": 61.5,
            "bone_mass_kg": 3.6,
            "water_pct": 53.5,
            "bmi": 23.5,
            "source": "withings",
            "raw_json": {}
        }
    ]

    with patch.object(handler, "fetch_measurements", return_value=mock_records):
        res = handler.sync_withings_data(days=30)
        assert res["success"] is True
        assert res["count"] == 1

    latest = test_db.get_latest_body_composition()
    assert latest["weight_kg"] == 80.2
    assert latest["fat_ratio_pct"] == 18.0


def test_sync_withings_incremental(tmp_path):
    test_db = GarminDatabase(db_path=tmp_path / "withings_inc_test.db")
    from datetime import datetime, timedelta
    yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
    test_db.set_metadata("last_withings_sync", yesterday)

    handler = WithingsDataHandler(
        client_id="dummy_id",
        client_secret="dummy_secret",
        refresh_token="dummy_refresh",
        access_token="dummy_access",
        db=test_db
    )

    with patch.object(handler, "fetch_measurements", return_value=[]) as mock_fetch:
        res = handler.sync_withings_data(days=365, force_full=False)
        mock_fetch.assert_called_once_with(days=365)


def test_sync_profile_weight_from_db(tmp_path):
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).parent.parent / "temp"))
    pytest.importorskip("HealthChatDesktop", reason="HealthChatDesktop is archived in temp/")
    from HealthChatDesktop import HealthChatApp
    test_db = GarminDatabase(db_path=tmp_path / "weight_sync_test.db")
    test_db.upsert_body_composition(
        date="2026-09-01",
        weight_kg=96.54,
        source="withings"
    )

    app = HealthChatApp.__new__(HealthChatApp)
    app.db = test_db
    app.user_weight_kg = 98.0
    app.save_config = MagicMock()
    app.charts_view = MagicMock()
    app.get_user_profile = MagicMock(return_value={'weight_kg': 96.5})

    app._sync_profile_weight_from_db()

    assert app.user_weight_kg == 96.5
    app.save_config.assert_called_once()
    app.charts_view.set_profile.assert_called_once()


