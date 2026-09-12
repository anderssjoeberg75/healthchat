"""
Unit tests for Web Security Hardening:
- S-15: CORS configuration with explicit origins and credentials restriction.
- TLS-2: Security headers middleware and cookie Secure flag handling.
"""

import os
import pytest
from fastapi.testclient import TestClient
from server import app, get_cookie_secure, get_allowed_origins
import auth


@pytest.fixture
def https_client():
    return TestClient(app, base_url="https://testserver")


def test_cors_disallowed_origin_gets_no_cors_header(https_client):
    """S-15: An origin not in ALLOWED_ORIGINS must not receive Access-Control-Allow-Origin."""
    res = https_client.get("/", headers={"Origin": "https://evil-attacker.example.com"})
    assert "access-control-allow-origin" not in res.headers


def test_cors_allowed_origin_gets_cors_header(https_client):
    """S-15: An allowed origin receives Access-Control-Allow-Origin and credentials flag."""
    res = https_client.get("/", headers={"Origin": "http://localhost:8000"})
    assert res.headers.get("access-control-allow-origin") == "http://localhost:8000"
    assert res.headers.get("access-control-allow-credentials") == "true"


def test_security_headers_present_on_root(https_client):
    """TLS-2: Verify all required security headers on response from /."""
    res = https_client.get("/")
    assert res.status_code == 200

    # 1. Strict-Transport-Security
    assert "strict-transport-security" in res.headers
    assert "max-age=31536000" in res.headers["strict-transport-security"]

    # 2. Content-Security-Policy
    assert "content-security-policy" in res.headers
    csp = res.headers["content-security-policy"]
    assert "default-src 'self'" in csp
    assert "https://cdn.jsdelivr.net" in csp  # For Chart.js

    # 3. X-Content-Type-Options
    assert res.headers.get("x-content-type-options") == "nosniff"

    # 4. X-Frame-Options
    assert res.headers.get("x-frame-options") == "DENY"

    # 5. Referrer-Policy
    assert res.headers.get("referrer-policy") == "strict-origin-when-cross-origin"


def test_cookie_secure_flag_enabled_by_default(monkeypatch, https_client):
    """TLS-2: Set-Cookie header contains Secure; HttpOnly; SameSite=... with default COOKIE_SECURE."""
    monkeypatch.delenv("COOKIE_SECURE", raising=False)
    assert get_cookie_secure() is True

    dummy_session = auth.UserSession(
        user_id=101,
        email="cookie_secure_test@example.com",
        dek=bytearray(b"0123456789abcdef0123456789abcdef"),
        encrypted_profile={}
    )
    monkeypatch.setattr("server.get_db_conn", lambda db: None)
    monkeypatch.setattr("auth.register_user", lambda conn, email, pwd, initial_profile: (101, "REC-KEY", dummy_session))

    res = https_client.post("/api/auth/register", json={
        "email": "cookie_secure_test@example.com",
        "password": "password12345"
    })
    assert res.status_code == 200
    set_cookie = res.headers.get("set-cookie", "")
    assert "healthchat_session=" in set_cookie
    assert "Secure" in set_cookie
    assert "HttpOnly" in set_cookie
    assert "SameSite=lax" in set_cookie or "SameSite=strict" in set_cookie


def test_cookie_secure_flag_disabled_when_cookie_secure_zero(monkeypatch, https_client):
    """TLS-2: Set-Cookie header does NOT contain Secure when COOKIE_SECURE=0."""
    monkeypatch.setenv("COOKIE_SECURE", "0")
    assert get_cookie_secure() is False

    dummy_session = auth.UserSession(
        user_id=102,
        email="cookie_insecure_test@example.com",
        dek=bytearray(b"0123456789abcdef0123456789abcdef"),
        encrypted_profile={}
    )
    monkeypatch.setattr("server.get_db_conn", lambda db: None)
    monkeypatch.setattr("auth.register_user", lambda conn, email, pwd, initial_profile: (102, "REC-KEY", dummy_session))

    res = https_client.post("/api/auth/register", json={
        "email": "cookie_insecure_test@example.com",
        "password": "password12345"
    })
    assert res.status_code == 200
    set_cookie = res.headers.get("set-cookie", "")
    assert "healthchat_session=" in set_cookie
    assert "Secure" not in set_cookie
    assert "HttpOnly" in set_cookie
