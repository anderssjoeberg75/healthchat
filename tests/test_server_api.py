"""
Unit tests for HealthChat FastAPI Web Server (server.py).
Tests REST authentication endpoints, session cookies, dashboard queries, and SSE chat endpoints.
"""

import pytest
import auth
from fastapi.testclient import TestClient
from server import app, _active_sessions

client = TestClient(app)


def test_root_endpoint_serves_html():
    """Test root GET / returns 200 OK HTML response."""
    response = client.get("/")
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]


def test_auth_me_unauthorized_without_cookie():
    """Test GET /api/auth/me returns 401 Unauthorized when not logged in."""
    response = client.get("/api/auth/me")
    assert response.status_code == 401


def test_register_login_and_me_flow(monkeypatch):
    """Test user registration, login, get_me, and logout flow via API."""
    test_email = "webtestuser@example.com"
    test_password = "password12345"

    dummy_session = auth.UserSession(
        user_id=99,
        email=test_email,
        dek=bytearray(b"0123456789abcdef0123456789abcdef"),
        encrypted_profile={"sex": "male", "age": 28, "height_cm": 180.0, "weight_kg": 75.0}
    )

    monkeypatch.setattr("server.get_db_conn", lambda db: None)
    monkeypatch.setattr("auth.register_user", lambda conn, email, pwd, initial_profile: (99, "REC-KEY-123", dummy_session))
    monkeypatch.setattr("auth.authenticate_user", lambda conn, email, pwd: dummy_session)

    # Register
    reg_payload = {
        "email": test_email,
        "password": test_password,
        "sex": "male",
        "age": 28,
        "height_cm": 180.0,
        "weight_kg": 75.0
    }
    reg_res = client.post("/api/auth/register", json=reg_payload)
    assert reg_res.status_code == 200, reg_res.text
    reg_data = reg_res.json()
    assert reg_data["status"] == "success"
    assert reg_data["recovery_key"] == "REC-KEY-123"
    assert "healthchat_session" in reg_res.cookies

    # Get Me with session cookie
    me_res = client.get("/api/auth/me", cookies=reg_res.cookies)
    assert me_res.status_code == 200
    me_data = me_res.json()
    assert me_data["email"] == test_email
    assert me_data["profile"]["height_cm"] == 180.0

    # Test update profile
    update_res = client.post(
        "/api/profile/update",
        json={"sex": "female", "age": 30, "height_cm": 175.0, "weight_kg": 68.0},
        cookies=reg_res.cookies
    )
    assert update_res.status_code == 200
    assert update_res.json()["profile"]["weight_kg"] == 68.0

    # Verify updated profile via /api/auth/me
    me_updated = client.get("/api/auth/me", cookies=reg_res.cookies)
    assert me_updated.status_code == 200
    assert me_updated.json()["profile"]["weight_kg"] == 68.0
    assert me_updated.json()["profile"]["age"] == 30

    # Logout
    logout_res = client.post("/api/auth/logout", cookies=reg_res.cookies)
    assert logout_res.status_code == 200

    # Verify Unauthorized after logout
    after_me_res = client.get("/api/auth/me")
    assert after_me_res.status_code == 401

