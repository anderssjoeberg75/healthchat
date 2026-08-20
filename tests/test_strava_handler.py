"""Tests for strava_handler.StravaHandler."""

import json
from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest

from garmin_db import GarminDatabase
from strava_handler import StravaHandler

def test_strava_token_save_and_load(tmp_path):
    test_db = GarminDatabase(db_path=tmp_path / "test.db")
    handler = StravaHandler(db=test_db, token_store_dir=tmp_path)
    
    assert handler.is_authenticated() is False
    
    tokens = {
        "access_token": "test_access_123",
        "refresh_token": "test_refresh_456",
        "expires_at": 1800000000,
        "client_id": "12345",
        "client_secret": "secret789"
    }
    handler.save_tokens(tokens)
    
    assert handler.is_authenticated() is True
    assert handler.access_token == "test_access_123"
    assert handler.refresh_token == "test_refresh_456"
    
    # Reload from disk
    new_handler = StravaHandler(db=test_db, token_store_dir=tmp_path)
    assert new_handler.is_authenticated() is True
    assert new_handler.access_token == "test_access_123"

def test_get_auth_url(tmp_path):
    test_db = GarminDatabase(db_path=tmp_path / "test.db")
    handler = StravaHandler(db=test_db, token_store_dir=tmp_path)
    
    url = handler.get_auth_url(client_id="99999", redirect_uri="http://localhost:8081/")
    assert "https://www.strava.com/oauth/authorize" in url
    assert "client_id=99999" in url
    assert "response_type=code" in url
    assert "scope=read%2Cactivity%3Aread_all" in url or "scope=read" in url

def test_parse_strava_csv(tmp_path):
    test_db = GarminDatabase(db_path=tmp_path / "test.db")
    handler = StravaHandler(db=test_db, token_store_dir=tmp_path)
    
    sample_csv = """Activity ID,Activity Date,Activity Name,Activity Type,Elapsed Time,Distance,Calories,Average Heart Rate,Max Heart Rate
10001,"Aug 19, 2026, 08:30:00 AM","Morgonlöpning","Run","00:45:00","7,5",450,145,168
10002,"Aug 20, 2026, 06:15:00 PM","Cykeltur","Ride","01:15:00","25000",700,130,155
"""
    count = handler._parse_strava_csv(sample_csv)
    assert count == 2
    
    activities = test_db.get_activities_history(days=30)
    assert len(activities) == 2
    
    run_act = [a for a in activities if a["activity_name"] == "Morgonlöpning"][0]
    assert run_act["distance_km"] == 7.5
    assert run_act["duration_min"] == 45.0
    assert run_act["calories"] == 450
    assert run_act["avg_hr"] == 145

def test_sync_strava_history(tmp_path):
    test_db = GarminDatabase(db_path=tmp_path / "test.db")
    handler = StravaHandler(db=test_db, token_store_dir=tmp_path)
    handler.save_tokens({
        "access_token": "valid_token",
        "refresh_token": "valid_refresh",
        "expires_at": 2000000000,
        "client_id": "123",
        "client_secret": "abc"
    })
    
    mock_activities = [
        {
            "id": 8881,
            "name": "Intervaller",
            "sport_type": "Run",
            "start_date_local": "2026-08-18T10:00:00Z",
            "distance": 5000,
            "elapsed_time": 1500,
            "kilojoules": 1500,
            "average_heartrate": 160,
            "max_heartrate": 182,
            "average_speed": 3.33
        }
    ]
    
    import threading
    done = threading.Event()
    with patch.object(handler, "fetch_activities", return_value=mock_activities):
        handler.sync_strava_history(days=30, on_complete=done.set)
        assert done.wait(timeout=5)
        
    activities = test_db.get_activities_history(days=30)
    assert len(activities) == 1
    assert activities[0]["activity_name"] == "Intervaller"
    assert activities[0]["distance_km"] == 5.0
    assert activities[0]["duration_min"] == 25.0
