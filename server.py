"""
FastAPI Web Server for HealthChat.
Exposes REST and SSE endpoints for HealthChat Web Application while preserving
the core domain logic, envelope encryption (AES-256-GCM + Argon2id), MariaDB backend,
and multi-provider AI engine.
"""

import os
import sys
import html
import secrets
import time
import uuid
import json
import shutil
import logging
import asyncio
import tempfile
import threading
from pathlib import Path
from typing import Dict, Any, Optional, List
from datetime import datetime, timedelta
from contextlib import contextmanager

from fastapi import FastAPI, Request, Response, HTTPException, status, Depends, Cookie, Query, Header
from fastapi.responses import HTMLResponse, StreamingResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, EmailStr

import garmin_db
from garmin_db import GarminDatabase
import auth
from auth import UserSession, mask_email
import crypto
import secret_store
import ai_client
from ai_client import AIClient
import calorie_calc
import hr_zones_calc
import profile_sync
import datasource_store

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("server")

app = FastAPI(
    title="HealthChat Web API",
    description="Secure AI-powered health & fitness analytics platform",
    version="4.1.0"
)

def get_allowed_origins() -> List[str]:
    raw = os.getenv("ALLOWED_ORIGINS", "").strip()
    if raw:
        return [o.strip() for o in raw.split(",") if o.strip()]
    return ["http://localhost:8000", "http://127.0.0.1:8000"]

def get_cookie_secure(request: Optional[Request] = None) -> bool:
    val = os.getenv("COOKIE_SECURE")
    if val is not None:
        return val.strip().lower() not in ("0", "false", "no")
    if request:
        proto = request.headers.get("x-forwarded-proto", "").lower()
        if request.url.scheme == "http" and proto != "https":
            return False
    return True

_allowed_origins = get_allowed_origins()
_allow_credentials = "*" not in _allowed_origins

# CORS Middleware (S-15) - also permits LAN IPs (192.168.x.x, 10.x.x.x, 127.0.0.1)
app.add_middleware(
    CORSMiddleware,
    allow_origins=_allowed_origins,
    allow_origin_regex=r"https?://(localhost|127\.0\.0\.1|192\.168\.\d+\.\d+|10\.\d+\.\d+\.\d+)(:\d+)?",
    allow_credentials=_allow_credentials,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type", "Authorization", "X-Requested-With", "Accept"],
)

# Security Headers Middleware (TLS-2)
@app.middleware("http")
async def add_security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; "
        "script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
        "style-src 'self' 'unsafe-inline'; "
        "img-src 'self' data:; "
        "connect-src 'self'; "
        "frame-ancestors 'none';"
    )
    return response


# In-memory active user sessions (S-13 Path A: DEK held strictly in memory, never in DB)
_active_sessions: Dict[str, UserSession] = {}
_session_expirations: Dict[str, datetime] = {}
_session_chat_histories: Dict[str, List[Dict[str, str]]] = {}
_user_chat_histories: Dict[int, List[Dict[str, str]]] = {}
_sessions_lock = threading.Lock()

SESSION_COOKIE_NAME = "healthchat_session"
SESSION_MAX_AGE_SECONDS = int(os.getenv("SESSION_MAX_AGE_SECONDS", str(86400 * 30)))  # 30 days


def store_active_session(session_id: str, session: UserSession, max_age: int = SESSION_MAX_AGE_SECONDS):
    """Store session in memory with TTL. DEK is never stored on disk or DB (S-13)."""
    now = datetime.now()
    expires_at = now + timedelta(seconds=max_age)
    with _sessions_lock:
        _active_sessions[session_id] = session
        _session_expirations[session_id] = expires_at


def remove_active_session(session_id: str) -> Optional[UserSession]:
    """Remove and zeroize session from memory."""
    with _sessions_lock:
        _session_expirations.pop(session_id, None)
        _session_chat_histories.pop(session_id, None)
        sess = _active_sessions.pop(session_id, None)
        if sess:
            sess.clear()
        return sess


def get_valid_session(session_id: str) -> Optional[UserSession]:
    """Retrieve active session if not expired, otherwise clean it up and return None."""
    with _sessions_lock:
        if session_id not in _active_sessions:
            return None
        expires_at = _session_expirations.get(session_id)
        if expires_at and datetime.now() > expires_at:
            sess = _active_sessions.pop(session_id, None)
            _session_expirations.pop(session_id, None)
            if sess:
                sess.clear()
            return None
        return _active_sessions[session_id]


def cleanup_expired_sessions(conn=None):
    """Clean up expired sessions from memory and database metadata."""
    now = datetime.now()
    with _sessions_lock:
        expired_ids = [sid for sid, exp in list(_session_expirations.items()) if now > exp]
        for sid in expired_ids:
            sess = _active_sessions.pop(sid, None)
            _session_expirations.pop(sid, None)
            if sess:
                sess.clear()

    if conn:
        try:
            is_mariadb = hasattr(conn, "ping")
            now_str = now.strftime("%Y-%m-%d %H:%M:%S")
            if is_mariadb:
                sql = "DELETE FROM user_sessions WHERE expires_at < NOW()"
                params = ()
            else:
                sql = "DELETE FROM user_sessions WHERE expires_at < ?"
                params = (now_str,)
            with _db_cursor(conn) as cur:
                cur.execute(sql, params)
            if hasattr(conn, "commit"):
                conn.commit()
        except Exception as e:
            logger.debug(f"Failed to prune expired user_sessions table rows: {e}")



# --- PYDANTIC SCHEMAS ---

class RegisterRequest(BaseModel):
    email: str
    password: str
    sex: Optional[str] = "male"
    height_cm: Optional[float] = 175.0
    age: Optional[int] = 30
    weight_kg: Optional[float] = 70.0


class LoginRequest(BaseModel):
    email: str
    password: str


class RecoverRequest(BaseModel):
    email: str
    recovery_key: str
    new_password: str


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str


class RotateRecoveryKeyRequest(BaseModel):
    current_password: str


class ProfileUpdateRequest(BaseModel):
    sex: Optional[str] = None
    height_cm: Optional[float] = None
    age: Optional[float] = None
    weight_kg: Optional[float] = None
    resting_hr: Optional[float] = None
    max_hr: Optional[float] = None
    fat_ratio_pct: Optional[float] = None
    muscle_mass_kg: Optional[float] = None
    bone_mass_kg: Optional[float] = None
    water_pct: Optional[float] = None
    bmi: Optional[float] = None
    injuries: Optional[str] = None




class ChatRequest(BaseModel):
    message: str
    provider: Optional[str] = "ollama"
    model: Optional[str] = None


# --- HELPER DEPENDENCIES ---

def get_db(require_mariadb: bool = True) -> GarminDatabase:
    """Instantiate GarminDatabase handler (enforces MariaDB in web mode)."""
    return GarminDatabase(require_mariadb=require_mariadb)


def bind_user_db(session: UserSession, require_mariadb: bool = True) -> GarminDatabase:
    """Create GarminDatabase bound to a copy of the authenticated user's DEK (Q-9 p4)."""
    db = GarminDatabase(require_mariadb=require_mariadb)
    dek_copy = bytearray(session.dek) if session.dek else None
    db.set_user_session(session.user_id, dek_copy)
    return db


def get_db_conn(db: GarminDatabase):
    """Get active database connection (MariaDB pool if available, otherwise SQLite fallback connection).
    Returns None if connection cannot be established (Q-9 p3)."""
    try:
        if db.is_mariadb and db.pool:
            return db.get_mariadb_conn()
        return db.get_connection()
    except Exception as e:
        logger.warning(f"Failed to acquire db connection: {e}")
        return None


@app.on_event("startup")
def startup_db_check():
    """Verify MariaDB connectivity on startup to prevent running with unsafe shared SQLite fallback (S-14)."""
    require_mariadb = os.environ.get("HEALTHCHAT_REQUIRE_MARIADB", "1").lower() not in ("0", "false", "no")
    if require_mariadb:
        try:
            db = GarminDatabase(require_mariadb=True)
            conn = db.get_mariadb_conn()
            with _db_cursor(conn) as cur:
                cur.execute("SELECT 1")
            conn.close()
            logger.info("MariaDB connectivity and connection pool verified on startup.")
        except Exception as e:
            logger.critical(f"FATAL: Kunde inte ansluta till MariaDB vid serverstart: {e}")
            raise RuntimeError(
                f"HealthChat Web kräver MariaDB i fleranvändarläge (S-14). "
                f"Fallback till SQLite är inte tillåtet. Fel: {e}"
            )


@app.exception_handler(RuntimeError)
async def runtime_database_error_handler(request: Request, exc: RuntimeError):
    msg = str(exc)
    if "MariaDB" in msg:
        logger.error(f"MariaDB unavailable on {request.url.path}: {msg}")
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={"detail": "Databasen är inte tillgänglig för tillfället (MariaDB krävs)."}
        )
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={"detail": msg}
    )



@contextmanager
def _db_cursor(conn):
    """Context manager for database cursors supporting both PyMySQL and sqlite3."""
    cur = conn.cursor()
    try:
        yield cur
    finally:
        try:
            cur.close()
        except Exception:
            pass


def init_sessions_table(conn):
    """Ensure user_sessions table exists in DB (WITHOUT DEK column per S-13)."""
    try:
        is_mariadb = hasattr(conn, "ping")
        sql = """
        CREATE TABLE IF NOT EXISTS user_sessions (
            session_id VARCHAR(64) PRIMARY KEY,
            user_id BIGINT NOT NULL,
            email VARCHAR(255) NOT NULL,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            expires_at DATETIME NOT NULL,
            INDEX idx_sessions_expires (expires_at),
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
        """ if is_mariadb else """
        CREATE TABLE IF NOT EXISTS user_sessions (
            session_id TEXT PRIMARY KEY,
            user_id INTEGER NOT NULL,
            email TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            expires_at TIMESTAMP NOT NULL
        );
        """
        with _db_cursor(conn) as cur:
            cur.execute(sql)
        if hasattr(conn, "commit"):
            try:
                conn.commit()
            except Exception:
                pass
    except Exception as e:
        logger.warning(f"Could not init user_sessions table: {e}")


def save_session_to_db(conn, session_id: str, session: UserSession, max_age: int = SESSION_MAX_AGE_SECONDS):
    """Store session in memory with TTL and persist metadata (without DEK) to DB (S-13)."""
    store_active_session(session_id, session, max_age=max_age)
    if not conn:
        return
    try:
        init_sessions_table(conn)
        cleanup_expired_sessions(conn)
        is_mariadb = hasattr(conn, "ping")
        placeholder = "%s" if is_mariadb else "?"
        expires_at = datetime.now() + timedelta(seconds=max_age)
        expires_val = expires_at if is_mariadb else expires_at.strftime("%Y-%m-%d %H:%M:%S")

        sql = (
            f"REPLACE INTO user_sessions (session_id, user_id, email, expires_at) VALUES ({placeholder}, {placeholder}, {placeholder}, {placeholder})"
            if is_mariadb else
            f"INSERT OR REPLACE INTO user_sessions (session_id, user_id, email, expires_at) VALUES ({placeholder}, {placeholder}, {placeholder}, {placeholder})"
        )
        with _db_cursor(conn) as cur:
            cur.execute(sql, (session_id, session.user_id, session.email, expires_val))
        if hasattr(conn, "commit"):
            try:
                conn.commit()
            except Exception:
                pass
    except Exception as e:
        logger.warning(f"Failed saving session metadata {session_id} to DB: {e}")


def load_session_from_db(conn, session_id: str) -> Optional[UserSession]:
    """Retrieve session from in-memory cache and verify DB expiration if present (S-13)."""
    session = get_valid_session(session_id)
    if not session:
        return None

    # Check DB expiration if record exists in user_sessions
    if conn:
        try:
            is_mariadb = hasattr(conn, "ping")
            placeholder = "%s" if is_mariadb else "?"
            sql = f"SELECT expires_at FROM user_sessions WHERE session_id = {placeholder}"
            with _db_cursor(conn) as cur:
                cur.execute(sql, (session_id,))
                row = cur.fetchone()
                if row:
                    exp = row["expires_at"] if isinstance(row, dict) else row[0]
                    if isinstance(exp, str):
                        exp = datetime.fromisoformat(exp.replace(" ", "T"))
                    if exp and datetime.now() > exp:
                        remove_active_session(session_id)
                        delete_session_from_db(conn, session_id)
                        return None
        except Exception as e:
            logger.debug(f"Error checking DB session expiration: {e}")

    # If profile is missing, fallback decrypt from users table
    if not session.encrypted_profile and conn:
        try:
            is_mariadb = hasattr(conn, "ping")
            placeholder = "%s" if is_mariadb else "?"
            with _db_cursor(conn) as cur:
                cur.execute(f"SELECT encrypted_profile, profile_nonce FROM users WHERE id = {placeholder}", (session.user_id,))
                u_row = cur.fetchone()
                if u_row:
                    enc_p = u_row["encrypted_profile"] if isinstance(u_row, dict) else u_row[0]
                    p_n = u_row["profile_nonce"] if isinstance(u_row, dict) else u_row[1]
                    if enc_p and p_n:
                        session.encrypted_profile = crypto.decrypt_payload(session.dek, enc_p, p_n)
        except Exception as ex:
            logger.warning(f"Failed fallback profile decrypt from users table: {ex}")

    return session


def delete_session_from_db(conn, session_id: str):
    """Delete session metadata from database table."""
    if not conn:
        return
    try:
        is_mariadb = hasattr(conn, "ping")
        placeholder = "%s" if is_mariadb else "?"
        sql = f"DELETE FROM user_sessions WHERE session_id = {placeholder}"
        with _db_cursor(conn) as cur:
            cur.execute(sql, (session_id,))
        if hasattr(conn, "commit"):
            try:
                conn.commit()
            except Exception:
                pass
    except Exception as e:
        logger.warning(f"Failed deleting session {session_id} from DB: {e}")


def get_current_session(
    healthchat_session: Optional[str] = Cookie(None),
    authorization: Optional[str] = Header(None)
) -> UserSession:
    """Dependency retrieving active UserSession from session cookie or Authorization header."""
    token = healthchat_session
    if not token and authorization:
        if authorization.lower().startswith("bearer "):
            token = authorization[7:].strip()
        else:
            token = authorization.strip()

    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Ej inloggad eller sessionen har löpt ut."
        )

    session = get_valid_session(token)
    if not session:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Ej inloggad eller sessionen har löpt ut."
        )

    if not session.encrypted_profile:
        db = get_db()
        conn = None
        try:
            conn = get_db_conn(db)
            fresh = load_session_from_db(conn, token)
            if fresh and fresh.encrypted_profile:
                return fresh
        finally:
            if conn:
                try:
                    conn.close()
                except Exception:
                    pass

    return session




# --- AUTH ENDPOINTS ---

@app.post("/api/auth/register")
def register(req: RegisterRequest, response: Response, request: Request):
    db = get_db()
    conn = get_db_conn(db)
    try:
        initial_profile = {
            "sex": req.sex,
            "height_cm": req.height_cm,
            "age": req.age,
            "weight_kg": req.weight_kg
        }
        user_id, recovery_key, session = auth.register_user(
            conn, req.email, req.password, initial_profile=initial_profile
        )
        session_id = str(uuid.uuid4())
        save_session_to_db(conn, session_id, session)
        
        response.set_cookie(
            key=SESSION_COOKIE_NAME,
            value=session_id,
            httponly=True,
            secure=get_cookie_secure(request),
            samesite="lax",
            max_age=SESSION_MAX_AGE_SECONDS
        )
        return {
            "status": "success",
            "message": "Konto skapat!",
            "session_id": session_id,
            "user_id": user_id,
            "recovery_key": recovery_key,
            "email": session.email
        }
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Registreringsfel: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Serverfel vid registrering. Försök igen senare.")
    finally:
        if conn:
            try:
                conn.close()
            except Exception:
                pass


@app.post("/api/auth/login")
def login(req: LoginRequest, response: Response, request: Request):
    db = get_db()
    conn = None
    try:
        conn = get_db_conn(db)
        session = auth.authenticate_user(conn, req.email, req.password)
        session_id = str(uuid.uuid4())
        save_session_to_db(conn, session_id, session)

        response.set_cookie(
            key=SESSION_COOKIE_NAME,
            value=session_id,
            httponly=True,
            secure=get_cookie_secure(request),
            samesite="lax",
            max_age=SESSION_MAX_AGE_SECONDS
        )
        return {
            "status": "success",
            "message": "Inloggningen lyckades!",
            "session_id": session_id,
            "user_id": session.user_id,
            "email": session.email,
            "profile": session.encrypted_profile or {}
        }
    except ValueError as e:
        raise HTTPException(status_code=401, detail=str(e))
    except Exception as e:
        logger.error(f"Inloggningsfel: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Serverfel vid inloggning: {e}")
    finally:
        if conn:
            try:
                conn.close()
            except Exception:
                pass


@app.post("/api/auth/logout")
def logout(response: Response, request: Request, healthchat_session: Optional[str] = Cookie(None), authorization: Optional[str] = Header(None)):
    token = healthchat_session
    if not token and authorization:
        if authorization.lower().startswith("bearer "):
            token = authorization[7:].strip()
        else:
            token = authorization.strip()

    if token:
        session = remove_active_session(token)
        if session:
            auth.clear_remembered_session(session.email)
        db = get_db()
        conn = None
        try:
            conn = get_db_conn(db)
            delete_session_from_db(conn, token)
        finally:
            if conn:
                try:
                    conn.close()
                except Exception:
                    pass
    response.delete_cookie(
        key=SESSION_COOKIE_NAME,
        httponly=True,
        secure=get_cookie_secure(request),
        samesite="lax"
    )
    return {"status": "success", "message": "Utloggad!"}


def auto_sync_user_profile(conn, session: UserSession, db: GarminDatabase):
    """Auto-fetch external/synced metrics (Garmin, Fitbit, Strava, Withings, DB)
    and auto-merge + persist into user session encrypted_profile in MariaDB."""
    try:
        ext_res = profile_sync.fetch_external_profile_metrics(db=db)
        metrics = ext_res.get("metrics", {})
        if metrics:
            current = dict(session.encrypted_profile or {})
            changed = False
            for k, v in metrics.items():
                if v is not None and v != 0 and v != "":
                    if current.get(k) != v:
                        current[k] = v
                        changed = True
            if changed:
                session.encrypted_profile = current
                if conn:
                    auth.update_user_profile(conn, session, current)
    except Exception as e:
        logger.warning(f"Auto-sync profile failed: {e}")
    return session.encrypted_profile or {}


@app.get("/api/auth/me")
def get_me(session: UserSession = Depends(get_current_session)):
    db = bind_user_db(session)
    conn = get_db_conn(db)
    try:
        prof = auto_sync_user_profile(conn, session, db)
        return {
            "user_id": session.user_id,
            "email": session.email,
            "profile": prof
        }
    finally:
        if conn:
            try:
                conn.close()
            except Exception:
                pass



@app.post("/api/auth/recover")
def recover_account(req: RecoverRequest):
    db = get_db()
    conn = get_db_conn(db)
    try:
        new_rec_key, session = auth.recover_account(conn, req.email, req.recovery_key, req.new_password)
        session.clear()
        return {
            "status": "success",
            "message": "Lösenordet har återställts!",
            "new_recovery_key": new_rec_key
        }
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    finally:
        if conn:
            conn.close()


# --- DASHBOARD & HEALTH DATA ENDPOINTS ---

@app.get("/api/dashboard/summary")
def get_dashboard_summary(
    days: int = Query(30, ge=1, le=3650),
    session: UserSession = Depends(get_current_session)
):
    db = bind_user_db(session)
    
    daily_summary_hist = db.get_daily_summary_history(days)
    sleep_hist = db.get_sleep_history(days)
    bb_hist = db.get_body_battery_history(days)
    stress_hist = db.get_stress_history(days)
    hrv_hist = db.get_hrv_history(days)
    activities_hist = db.get_activities_history(days)
    body_comp_latest = db.get_latest_body_composition()
    body_comp_hist = db.get_body_composition_history(days)
    calorie_burn_hist = db.get_calorie_burn_history(days)
    
    # Calculate today's calorie burn estimate using calorie_calc
    today_str = datetime.now().strftime("%Y-%m-%d")
    daily_sum_today = db.get_daily_summary(today_str) or {}
    
    # Extract Garmin device BMR from raw_json matching desktop charts_view.py
    bmr_override = 0.0
    raw = daily_sum_today.get("raw_json")
    if raw:
        try:
            rd = json.loads(raw) if isinstance(raw, str) else raw
            device_bmr = float(rd.get("bmrKilocalories", 0) or 0)
            frac = calorie_calc.day_fraction_elapsed()
            if device_bmr > 0 and frac > 0.05:
                bmr_override = device_bmr / frac
            else:
                bmr_override = device_bmr
        except Exception:
            bmr_override = 0.0

    workout_cal = 0
    workout_steps = 0
    for a in (activities_hist or []):
        if str(a.get("date") or a.get("start_time") or "")[:10] == today_str:
            try:
                workout_cal += int(float(a.get("calories") or 0))
            except (TypeError, ValueError):
                pass
            act_steps = 0
            raw_act = a.get("raw_json")
            if raw_act:
                try:
                    ra = json.loads(raw_act) if isinstance(raw_act, str) else raw_act
                    act_steps = int(ra.get("steps") or ra.get("totalSteps") or 0)
                except Exception:
                    act_steps = 0
            if not act_steps:
                act_steps = int(a.get("steps") or a.get("total_steps") or 0)
            if not act_steps:
                act_type = str(a.get("activity_type") or "").lower()
                if any(k in act_type for k in ("run", "walk", "hike", "löp", "gång", "jogg")):
                    dist = float(a.get("distance_km") or 0.0)
                    if dist > 0:
                        act_steps = int(dist * 1300)
            workout_steps += max(0, act_steps)

    conn = get_db_conn(db)
    try:
        profile = auto_sync_user_profile(conn, session, db)
    finally:
        if conn:
            try:
                conn.close()
            except Exception:
                pass

    weight = (
        profile.get("weight_kg")
        or (body_comp_latest or {}).get("weight_kg")
        or 70.0
    )

    
    burn_estimate = calorie_calc.estimate_daily_burn(
        weight_kg=weight,
        height_cm=profile.get("height_cm"),
        age_years=profile.get("age"),
        sex=profile.get("sex", "male"),
        steps=daily_sum_today.get("total_steps", 0),
        workout_steps=workout_steps,
        workout_calories=workout_cal,
        bmr_override=bmr_override,
        is_today=True
    )

    hr_calc = hr_zones_calc.calculate_hr_zones(
        age=profile.get("age", 40),
        resting_hr=profile.get("resting_hr"),
        max_hr_override=profile.get("max_hr"),
        sex=profile.get("sex", "male")
    )

    return {
        "today_date": today_str,
        "profile": profile,
        "latest_body_comp": body_comp_latest,
        "calorie_burn_today": burn_estimate,
        "sleep_latest": sleep_hist[-1] if sleep_hist else None,
        "bb_latest": (
            {**bb_hist[-1], "highest_level": bb_hist[-1].get("highest") or bb_hist[-1].get("highest_level")}
            if bb_hist else None
        ),
        "stress_latest": stress_hist[-1] if stress_hist else None,
        "hrv_latest": hrv_hist[-1] if hrv_hist else None,
        "activities_recent": activities_hist[:10],
        "hr_zones": hr_calc,
        "history": {
            "daily_summary": daily_summary_hist,
            "sleep": sleep_hist,
            "body_battery": bb_hist,
            "stress": stress_hist,
            "hrv": hrv_hist,
            "activities": activities_hist,
            "body_composition": body_comp_hist,
            "calorie_burn": calorie_burn_hist
        }
    }


# --- AI CHAT ENDPOINT (SSE STREAMING) ---

import secret_store

@app.post("/api/ai/chat")
async def chat_stream(
    req: ChatRequest,
    healthchat_session: Optional[str] = Cookie(None),
    session: UserSession = Depends(get_current_session)
):
    db = bind_user_db(session)
    activities = db.get_activities_history(30)
    sleep = db.get_sleep_history(7)
    hrv = db.get_hrv_history(7)
    body_comp = db.get_latest_body_composition() or {}
    
    context_lines = [f"Användar-ID: {session.user_id}"]
    
    profile = session.encrypted_profile or {}
    if profile.get("injuries"):
        context_lines.append(f"⚠️ KÄNDA SKADOR / FYSISKA BEGRÄNSNINGAR: {profile.get('injuries')}")
        context_lines.append(
            "VIKTIGT OM SKADOR & TRÄNINGSPASS: Användaren har ovanstående skador/begränsningar angivna. "
            "Du MÅSTE ta särskild hänsyn till detta vid ALLA tränings-, pass- och övningsrekommendationer! "
            "Föreslå skonsamma alternativ, anpassa intensitet/volym och varna uttryckligen för övningar "
            "eller rörelser som kan belasta det skadade området negativt."
        )
    if profile.get("age"):
        context_lines.append(f"Ålder: {profile.get('age')} år")
    if profile.get("resting_hr"):
        context_lines.append(f"Vilopuls: {profile.get('resting_hr')} bpm")
    if profile.get("max_hr"):
        context_lines.append(f"Maxpuls: {profile.get('max_hr')} bpm")
    if profile.get("bmi"):
        context_lines.append(f"BMI: {profile.get('bmi')}")

    if body_comp.get("weight_kg"):
        context_lines.append(f"Vikt: {body_comp.get('weight_kg')} kg (Fett%: {body_comp.get('fat_ratio_pct', 'N/A')}%)")
    elif profile.get("weight_kg"):
        context_lines.append(f"Vikt: {profile.get('weight_kg')} kg")
    if activities:
        context_lines.append(f"Senaste aktiviteter (30d): {len(activities)} st. Senaste: {activities[0].get('activity_name', 'Träning')} ({activities[0].get('distance_km', 0)} km, {activities[0].get('duration_min', 0)} min)")
    if sleep:
        context_lines.append(f"Senaste sömn: {sleep[-1].get('total_sleep_hours', 0)}h (Score: {sleep[-1].get('sleep_score', 'N/A')})")
    if hrv:
        context_lines.append(f"Senaste HRV: {hrv[-1].get('last_night_avg', 'N/A')} ms (Status: {hrv[-1].get('status', 'N/A')})")
    
    garmin_context = "\n".join(context_lines)
    
    # All AI-chatt körs mot lokal Ollama-server på 192.168.107.15 (eller OLLAMA_BASE_URL i miljövariabler)
    ollama_url = (
        secret_store.get_secret("ollama_base_url")
        or os.environ.get("OLLAMA_BASE_URL")
        or "http://192.168.107.15:11436"
    )
    ollama_model = (
        req.model
        or secret_store.get_secret("ollama_model")
        or os.environ.get("OLLAMA_MODEL")
        or "gemma4:12b"
    )

    client = AIClient(
        provider="ollama",
        api_key="",
        model=ollama_model,
        ollama_base_url=ollama_url
    )

    # Restore prior conversation history for this active session or user
    hist_key = healthchat_session or f"user_{session.user_id}"
    if hist_key in _session_chat_histories:
        client.conversation_history = list(_session_chat_histories[hist_key])
    elif session.user_id in _user_chat_histories:
        client.conversation_history = list(_user_chat_histories[session.user_id])

    async def event_generator():
        try:
            import queue
            q = queue.Queue()
            SENTINEL = object()

            def producer():
                try:
                    if hasattr(client, "chat_stream"):
                        for chunk in client.chat_stream(req.message, garmin_context=garmin_context):
                            q.put(chunk)
                    else:
                        resp = client.chat(req.message, garmin_context=garmin_context)
                        q.put(resp)
                except Exception as ex:
                    q.put(ex)
                finally:
                    q.put(SENTINEL)

            loop = asyncio.get_event_loop()
            loop.run_in_executor(None, producer)

            while True:
                item = await loop.run_in_executor(None, q.get)
                if item is SENTINEL:
                    break
                if isinstance(item, Exception):
                    raise item
                if item:
                    yield f"data: {json.dumps({'chunk': item}, ensure_ascii=False)}\n\n"

            # Persist updated conversation history
            _user_chat_histories[session.user_id] = list(client.conversation_history)
            if healthchat_session:
                _session_chat_histories[healthchat_session] = list(client.conversation_history)

            yield f"data: {json.dumps({'done': True})}\n\n"
        except Exception as e:
            logger.error(f"Error streaming AI response: {e}")
            yield f"data: {json.dumps({'error': str(e)}, ensure_ascii=False)}\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream")


@app.get("/api/ai/chat/history")
def get_chat_history(
    healthchat_session: Optional[str] = Cookie(None),
    session: UserSession = Depends(get_current_session)
):
    """Retrieve chat history for the current session or user."""
    hist = []
    if healthchat_session and healthchat_session in _session_chat_histories:
        hist = _session_chat_histories[healthchat_session]
    elif session.user_id in _user_chat_histories:
        hist = _user_chat_histories[session.user_id]
    return {"history": hist}


@app.post("/api/ai/chat/clear")
def clear_chat_history(
    healthchat_session: Optional[str] = Cookie(None),
    session: UserSession = Depends(get_current_session)
):
    """Clear chat history for the current session and user."""
    if healthchat_session:
        _session_chat_histories.pop(healthchat_session, None)
    _user_chat_histories.pop(session.user_id, None)
    return {"status": "cleared"}


# --- PROFILE ENDPOINTS ---

@app.post("/api/profile/update")
@app.put("/api/user/profile")
@app.post("/api/user/profile")
def update_profile(
    req: ProfileUpdateRequest,
    healthchat_session: Optional[str] = Cookie(None),
    session: UserSession = Depends(get_current_session)
):
    db = bind_user_db(session)
    conn = get_db_conn(db)
    try:
        current_profile = session.encrypted_profile or {}
        if req.sex is not None:
            current_profile["sex"] = req.sex
        if req.height_cm is not None:
            current_profile["height_cm"] = req.height_cm
        if req.age is not None:
            current_profile["age"] = req.age
        if req.weight_kg is not None:
            current_profile["weight_kg"] = req.weight_kg
        if req.resting_hr is not None:
            current_profile["resting_hr"] = req.resting_hr
        if req.max_hr is not None:
            current_profile["max_hr"] = req.max_hr
        if req.fat_ratio_pct is not None:
            current_profile["fat_ratio_pct"] = req.fat_ratio_pct
        if req.muscle_mass_kg is not None:
            current_profile["muscle_mass_kg"] = req.muscle_mass_kg
        if req.bone_mass_kg is not None:
            current_profile["bone_mass_kg"] = req.bone_mass_kg
        if req.water_pct is not None:
            current_profile["water_pct"] = req.water_pct
        if req.bmi is not None:
            current_profile["bmi"] = req.bmi
        if req.injuries is not None:
            current_profile["injuries"] = req.injuries.strip()

        if (not current_profile.get("bmi") or float(current_profile.get("bmi") or 0) == 0) and current_profile.get("height_cm") and current_profile.get("weight_kg"):
            try:
                h_m = float(current_profile["height_cm"]) / 100.0
                w_k = float(current_profile["weight_kg"])
                if h_m > 0 and w_k > 0:
                    current_profile["bmi"] = round(w_k / (h_m ** 2), 1)
            except Exception:
                pass

            
        if conn:
            auth.update_user_profile(conn, session, current_profile)
            if healthchat_session:
                save_session_to_db(conn, healthchat_session, session)
        else:
            session.encrypted_profile = current_profile
        if healthchat_session:
            _active_sessions[healthchat_session] = session
        return {"status": "success", "profile": current_profile}
    finally:
        if conn:
            conn.close()


@app.get("/api/user/profile/refresh")
@app.post("/api/user/profile/refresh")
@app.get("/api/user/profile/fetch_external")
@app.post("/api/user/profile/fetch_external")
def fetch_external_profile(session: UserSession = Depends(get_current_session)):
    """Fetch and refresh profile metrics from local encrypted health database history or connected sources (Q-1)."""
    db = bind_user_db(session)
    res = profile_sync.fetch_external_profile_metrics(db=db)
    return {
        "status": "success",
        "metrics": res.get("metrics", {}),
        "sources": res.get("sources", [])
    }



@app.post("/api/profile/change_password")
@app.post("/api/user/password")
def change_password(req: ChangePasswordRequest, session: UserSession = Depends(get_current_session)):
    db = bind_user_db(session)
    conn = get_db_conn(db)
    try:
        if conn:
            auth.change_user_password(conn, session.user_id, req.current_password, req.new_password)
        return {"status": "success", "message": "Lösenordet har ändrats!"}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    finally:
        if conn:
            conn.close()


@app.post("/api/user/rotate_recovery_key")
def rotate_recovery_key(req: RotateRecoveryKeyRequest, session: UserSession = Depends(get_current_session)):
    db = bind_user_db(session)
    conn = get_db_conn(db)
    try:
        new_key = auth.rotate_recovery_key(conn, session.user_id, req.current_password)
        return {"status": "success", "new_recovery_key": new_key}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    finally:
        if conn:
            conn.close()


class DeleteAccountRequest(BaseModel):
    current_password: Optional[str] = None


@app.delete("/api/user/delete_account")
@app.post("/api/user/delete_account")
def delete_account(
    response: Response,
    request: Request,
    req: Optional[DeleteAccountRequest] = None,
    healthchat_session: Optional[str] = Cookie(None),
    authorization: Optional[str] = Header(None),
    session: UserSession = Depends(get_current_session)
):
    db = bind_user_db(session)
    conn = get_db_conn(db)
    try:
        if conn:
            pw = req.current_password if req else None
            auth.delete_user_account(conn, session.user_id, current_password=pw)
        token = healthchat_session
        if not token and authorization:
            token = authorization[7:].strip() if authorization.lower().startswith("bearer ") else authorization.strip()
        if token:
            remove_active_session(token)
            delete_session_from_db(conn, token)
        if response:
            response.delete_cookie(
                key=SESSION_COOKIE_NAME,
                httponly=True,
                secure=get_cookie_secure(request),
                samesite="lax"
            )
        return {"status": "success", "message": "Konto raderat!"}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    finally:
        if conn:
            conn.close()


# --- DATAKÄLLOR: EXTERNA TJÄNSTER (STRAVA, GARMIN, WITHINGS, FITBIT) ---

# Garmin Connect logs in with email/password (+ optional MFA) instead of OAuth, so an
# in-flight login must stay alive between the first request and the MFA request.
GARMIN_PENDING_TTL_SECONDS = 600
_pending_garmin: Dict[int, Dict[str, Any]] = {}
_pending_garmin_lock = threading.Lock()
# garth keeps its client in module state; datasource_store owns the shared lock.
_garmin_auth_lock = datasource_store.GARMIN_AUTH_LOCK

# In-memory state for background sync jobs, polled by the frontend.
_sync_jobs: Dict[str, Dict[str, Any]] = {}
_sync_jobs_lock = threading.Lock()


class DatasourceCredentialsRequest(BaseModel):
    client_id: Optional[str] = None
    client_secret: Optional[str] = None


class DatasourceSyncRequest(BaseModel):
    days: Optional[int] = None
    force_full: bool = False


class GarminConnectRequest(BaseModel):
    email: Optional[str] = None
    password: Optional[str] = None
    mfa_code: Optional[str] = None
    save_credentials: bool = True


def get_public_base_url(request: Request) -> str:
    """Public origin used to build OAuth redirect URIs (override with PUBLIC_BASE_URL)."""
    configured = os.environ.get("PUBLIC_BASE_URL", "").strip()
    if configured:
        return configured.rstrip("/")
    return str(request.base_url).rstrip("/")


def datasource_callback_url(request: Request, provider: str) -> str:
    return f"{get_public_base_url(request)}/api/datasources/{provider}/callback"


def require_provider(provider: str) -> str:
    if not datasource_store.is_valid_provider(provider):
        raise HTTPException(status_code=404, detail=f"Okänd datakälla: {provider}")
    return provider


def compare_oauth_state(stored: str, received: str) -> bool:
    """Constant-time comparison of OAuth CSRF state tokens."""
    return secrets.compare_digest(str(stored).strip(), str(received).strip())


@contextmanager
def datasource_errors(context: str):
    """
    Turn unexpected failures in a datasource endpoint into a readable JSON error.

    Without this an unhandled exception becomes a bare 500 with a plain-text body,
    which the frontend cannot parse into a message - the user just sees that the
    call failed, and the cause only exists in the server log.
    """
    try:
        yield
    except HTTPException:
        raise
    except Exception as e:
        # The exception message can carry connection strings or URLs with tokens, so
        # only the exception type and a correlation id go back to the client (S-15).
        error_id = uuid.uuid4().hex[:12]
        logger.exception(f"Datasource error ({context}) [felkod {error_id}]")
        raise HTTPException(
            status_code=500,
            detail=(
                f"{context} misslyckades ({type(e).__name__}). "
                f"Felkod {error_id} - detaljerna finns i serverloggen."
            )
        )


@contextmanager
def datasource_session(session: UserSession):
    """Yield (db, conn) with the user_datasources table guaranteed to exist."""
    db = bind_user_db(session)
    conn = get_db_conn(db)
    if conn is None:
        raise HTTPException(status_code=503, detail="Databasen är inte tillgänglig för tillfället.")
    try:
        datasource_store.ensure_table(conn)
        yield db, conn
    finally:
        try:
            conn.close()
        except Exception:
            pass


def _cleanup_pending_garmin(user_id: Optional[int] = None):
    """Drop expired (or explicitly named) in-flight Garmin logins and their token dirs."""
    now = time.time()
    with _pending_garmin_lock:
        for uid in list(_pending_garmin.keys()):
            pending = _pending_garmin[uid]
            expired = (now - pending.get("created_at", 0)) > GARMIN_PENDING_TTL_SECONDS
            if uid == user_id or expired:
                token_dir = pending.get("token_dir")
                if token_dir:
                    shutil.rmtree(str(token_dir), ignore_errors=True)
                _pending_garmin.pop(uid, None)


@app.get("/api/datasources")
def list_datasources(request: Request, session: UserSession = Depends(get_current_session)):
    """List connection status for every supported external data source."""
    with datasource_errors("Hamtningen av datakallor"), datasource_session(session) as (_db, conn):
        providers = datasource_store.list_status(
            conn, session.user_id, bytes(session.dek),
            lambda p: datasource_callback_url(request, p)
        )
    return {"status": "success", "providers": providers}


@app.post("/api/datasources/{provider}/credentials")
def save_datasource_credentials(
    provider: str,
    req: DatasourceCredentialsRequest,
    request: Request,
    session: UserSession = Depends(get_current_session)
):
    """Store API credentials (Client ID / Client Secret) for an OAuth data source."""
    require_provider(provider)
    meta = datasource_store.PROVIDERS[provider]
    if meta["auth_kind"] != "oauth":
        raise HTTPException(
            status_code=400,
            detail=f"{meta['name']} ansluts med inloggningsuppgifter, inte med Client ID/Secret."
        )

    client_id = (req.client_id or "").strip()
    client_secret = (req.client_secret or "").strip()
    if not client_id:
        raise HTTPException(status_code=400, detail="Client ID måste anges.")

    dek = bytes(session.dek)
    with datasource_errors("Sparandet av API-uppgifter"), datasource_session(session) as (_db, conn):
        record = datasource_store.load_record(conn, session.user_id, dek, provider)
        payload = dict(record["payload"])
        payload["client_id"] = client_id
        if client_secret:
            payload["client_secret"] = client_secret
        if not payload.get("client_secret"):
            raise HTTPException(status_code=400, detail="Client Secret måste anges.")

        datasource_store.save_record(conn, session.user_id, dek, provider, payload)
        record = datasource_store.load_record(conn, session.user_id, dek, provider)
        status_obj = datasource_store.public_status(
            provider, record, datasource_callback_url(request, provider)
        )
    return {
        "status": "success",
        "message": f"Uppgifterna för {meta['name']} är sparade. Klicka på Anslut för att godkänna åtkomsten.",
        "provider_status": status_obj
    }


@app.post("/api/datasources/{provider}/authorize")
def authorize_datasource(
    provider: str,
    request: Request,
    session: UserSession = Depends(get_current_session)
):
    """Build the provider OAuth authorization URL and persist state/PKCE verifier."""
    require_provider(provider)
    meta = datasource_store.PROVIDERS[provider]
    if meta["auth_kind"] != "oauth":
        raise HTTPException(
            status_code=400,
            detail=f"{meta['name']} ansluts med inloggningsuppgifter, inte via OAuth."
        )

    dek = bytes(session.dek)
    redirect_uri = datasource_callback_url(request, provider)

    with datasource_errors("Auktoriseringen"), datasource_session(session) as (db, conn):
        record = datasource_store.load_record(conn, session.user_id, dek, provider)
        payload = dict(record["payload"])
        if not payload.get("client_id") or not payload.get("client_secret"):
            raise HTTPException(
                status_code=400,
                detail=f"Spara Client ID och Client Secret för {meta['name']} innan du ansluter."
            )

        with datasource_store.temp_token_dir() as token_dir:
            handler = datasource_store.build_handler(provider, db, payload, token_dir)
            auth_url = handler.get_auth_url(payload["client_id"], redirect_uri=redirect_uri)
            payload["oauth_state"] = handler.current_state
            payload["redirect_uri"] = redirect_uri
            if getattr(handler, "code_verifier", None):
                payload["code_verifier"] = handler.code_verifier

        datasource_store.save_record(conn, session.user_id, dek, provider, payload)

    return {"status": "success", "auth_url": auth_url, "redirect_uri": redirect_uri}


def _callback_page(provider: str, ok: bool, message: str) -> HTMLResponse:
    """Render the small landing page the provider redirects back to."""
    meta = datasource_store.PROVIDERS.get(provider, {"name": provider, "icon": "🔌"})
    safe_message = html.escape(message)
    safe_name = html.escape(str(meta.get("name", provider)))
    safe_provider = html.escape(provider)
    color = "#10B981" if ok else "#EF4444"
    heading = f"✅ {safe_name} ansluten!" if ok else f"❌ Kunde inte ansluta till {safe_name}"
    target = f"/?datakalla={safe_provider}&status={'ok' if ok else 'error'}"
    body = f"""<!DOCTYPE html>
<html lang="sv">
<head>
  <meta charset="utf-8">
  <title>{safe_name} – HealthChat</title>
  <meta http-equiv="refresh" content="4;url={target}">
</head>
<body style="font-family: 'Segoe UI', sans-serif; text-align:center; padding-top:60px; background:#F3F4F6;">
  <div style="background:#fff; max-width:520px; margin:0 auto; padding:40px; border-radius:12px; box-shadow:0 4px 12px rgba(0,0,0,0.08);">
    <h2 style="color:{color}; margin-bottom:10px;">{heading}</h2>
    <p style="color:#4B5563; font-size:16px;">{safe_message}</p>
    <p style="color:#6B7280; font-size:14px;">Du skickas tillbaka till HealthChat automatiskt.</p>
    <a href="{target}" style="color:#0078D4; font-weight:600;">Tillbaka till Datakällor</a>
  </div>
</body>
</html>"""
    return HTMLResponse(content=body, status_code=200 if ok else 400)


@app.get("/api/datasources/{provider}/callback", response_class=HTMLResponse)
def datasource_oauth_callback(
    provider: str,
    request: Request,
    code: Optional[str] = Query(None),
    state: Optional[str] = Query(None),
    error: Optional[str] = Query(None),
    healthchat_session: Optional[str] = Cookie(None)
):
    """OAuth redirect target: verify state, exchange the code and store the tokens."""
    if not datasource_store.is_valid_provider(provider):
        return _callback_page(provider, False, "Okänd datakälla.")
    meta = datasource_store.PROVIDERS[provider]

    session = get_valid_session(healthchat_session) if healthchat_session else None
    if session is None:
        return _callback_page(provider, False, "Din session har gått ut. Logga in igen och upprepa anslutningen.")

    if error:
        return _callback_page(provider, False, f"{meta['name']} nekade åtkomsten ({error}).")
    if not code:
        return _callback_page(provider, False, "Ingen auktoriseringskod mottogs.")

    dek = bytes(session.dek)
    try:
        with datasource_session(session) as (db, conn):
            record = datasource_store.load_record(conn, session.user_id, dek, provider)
            payload = dict(record["payload"])

            stored_state = payload.get("oauth_state")
            if not stored_state or not state or not compare_oauth_state(stored_state, state):
                return _callback_page(
                    provider, False,
                    "Säkerhetskontrollen (state) misslyckades. Starta anslutningen igen från Datakällor."
                )

            redirect_uri = payload.get("redirect_uri") or datasource_callback_url(request, provider)

            with datasource_store.temp_token_dir() as token_dir:
                handler = datasource_store.build_handler(provider, db, payload, token_dir)
                handler.exchange_code_for_token(
                    code,
                    payload.get("client_id", ""),
                    payload.get("client_secret", ""),
                    redirect_uri=redirect_uri
                )
                tokens = datasource_store.collect_tokens(provider, handler)

            if not tokens.get("access_token") and not tokens.get("refresh_token"):
                return _callback_page(provider, False, f"{meta['name']} lämnade inga giltiga tokens.")

            payload.update(tokens)
            payload.pop("oauth_state", None)
            payload.pop("code_verifier", None)
            datasource_store.save_record(conn, session.user_id, dek, provider, payload, connected=True)

        logger.info(f"Datasource {provider} connected for user {session.user_id}")
        return _callback_page(
            provider, True,
            f"Ditt {meta['name']}-konto är anslutet. Kör en synkronisering under Datakällor för att hämta data."
        )
    except Exception as e:
        logger.error(f"OAuth callback failed for {provider}: {e}")
        return _callback_page(provider, False, f"Anslutningen misslyckades: {e}")


@app.post("/api/datasources/garmin/connect")
def connect_garmin(
    req: GarminConnectRequest,
    request: Request,
    session: UserSession = Depends(get_current_session)
):
    """Log in to Garmin Connect with email/password, handling the MFA round trip."""
    dek = bytes(session.dek)
    mfa_code = (req.mfa_code or "").strip()
    _cleanup_pending_garmin()

    with datasource_errors("Garmin-anslutningen"), datasource_session(session) as (db, conn):
        record = datasource_store.load_record(conn, session.user_id, dek, "garmin")
        payload = dict(record["payload"])

        if mfa_code:
            with _pending_garmin_lock:
                pending = _pending_garmin.get(session.user_id)
            if not pending:
                raise HTTPException(
                    status_code=400,
                    detail="Ingen pågående Garmin-inloggning hittades. Börja om med e-post och lösenord."
                )
            handler = pending["handler"]
            token_dir = pending["token_dir"]
            email = pending.get("email", "")
            password = pending.get("password", "")
            save_credentials = pending.get("save_credentials", True)
            with _garmin_auth_lock:
                result = handler.submit_mfa(mfa_code)
        else:
            email = (req.email or payload.get("email") or "").strip()
            password = req.password or payload.get("password") or ""
            save_credentials = bool(req.save_credentials)
            if not email or not password:
                raise HTTPException(status_code=400, detail="Ange både e-postadress och lösenord för Garmin Connect.")

            _cleanup_pending_garmin(session.user_id)
            token_dir = Path(tempfile.mkdtemp(prefix="healthchat_garmin_"))
            login_payload = dict(payload)
            login_payload["email"] = email
            login_payload["password"] = password
            handler = datasource_store.build_handler("garmin", db, login_payload, token_dir)
            with _garmin_auth_lock:
                result = handler.authenticate()

        payload["email"] = email
        if save_credentials:
            payload["password"] = password
        else:
            payload.pop("password", None)

        if result.get("mfa_required"):
            with _pending_garmin_lock:
                _pending_garmin[session.user_id] = {
                    "handler": handler,
                    "token_dir": token_dir,
                    "email": email,
                    "password": password,
                    "save_credentials": save_credentials,
                    "created_at": time.time(),
                }
            datasource_store.save_record(conn, session.user_id, dek, "garmin", payload, connected=False)
            return {
                "status": "mfa_required",
                "message": "Garmin kräver en engångskod (MFA). Ange koden från din autentiseringsapp."
            }

        if not result.get("success"):
            _cleanup_pending_garmin(session.user_id)
            datasource_store.save_record(conn, session.user_id, dek, "garmin", payload, connected=False)
            raise HTTPException(
                status_code=400,
                detail=result.get("error") or "Inloggningen på Garmin Connect misslyckades."
            )

        tokens = datasource_store.collect_tokens("garmin", handler, token_dir)
        payload.update(tokens)
        datasource_store.save_record(conn, session.user_id, dek, "garmin", payload, connected=True)
        _cleanup_pending_garmin(session.user_id)

        record = datasource_store.load_record(conn, session.user_id, dek, "garmin")
        status_obj = datasource_store.public_status(
            "garmin", record, datasource_callback_url(request, "garmin")
        )

    logger.info(f"Garmin Connect linked for user {session.user_id}")
    return {
        "status": "connected",
        "message": "Garmin Connect är anslutet. Kör en synkronisering för att hämta din hälsodata.",
        "provider_status": status_obj
    }


@app.post("/api/datasources/{provider}/disconnect")
def disconnect_datasource(
    provider: str,
    request: Request,
    session: UserSession = Depends(get_current_session)
):
    """Delete all stored credentials and tokens for one data source."""
    require_provider(provider)
    meta = datasource_store.PROVIDERS[provider]
    if provider == "garmin":
        _cleanup_pending_garmin(session.user_id)

    with datasource_errors("Bortkopplingen"), datasource_session(session) as (_db, conn):
        datasource_store.delete_record(conn, session.user_id, provider)
        record = datasource_store.load_record(conn, session.user_id, bytes(session.dek), provider)
        status_obj = datasource_store.public_status(
            provider, record, datasource_callback_url(request, provider)
        )

    with _sync_jobs_lock:
        _sync_jobs.pop(f"{session.user_id}:{provider}", None)

    logger.info(f"Datasource {provider} disconnected for user {session.user_id}")
    return {
        "status": "success",
        "message": f"{meta['name']} är bortkopplad. Redan hämtad hälsodata ligger kvar i databasen.",
        "provider_status": status_obj
    }


def _sync_job_key(user_id: int, provider: str) -> str:
    return f"{user_id}:{provider}"


def _set_sync_job(key: str, **fields):
    with _sync_jobs_lock:
        job = _sync_jobs.setdefault(key, {})
        job.update(fields)


def build_worker_db(user_id: int, dek: bytes) -> GarminDatabase:
    """GarminDatabase bound to a user's DEK copy, for use outside a request scope."""
    db = GarminDatabase(require_mariadb=True)
    db.set_user_session(user_id, bytearray(dek))
    return db


def _run_datasource_sync(user_id: int, dek: bytes, provider: str, days: Optional[int], force_full: bool):
    """Background worker: sync one provider and persist refreshed tokens."""
    key = _sync_job_key(user_id, provider)
    conn = None
    try:
        db = build_worker_db(user_id, dek)
        conn = get_db_conn(db)
        if conn is None:
            _set_sync_job(key, state="error", message="Databasen är inte tillgänglig.")
            return

        datasource_store.ensure_table(conn)
        record = datasource_store.load_record(conn, user_id, dek, provider)
        payload = dict(record["payload"])

        if not datasource_store.has_tokens(provider, payload):
            _set_sync_job(
                key, state="error",
                message=f"{datasource_store.PROVIDERS[provider]['name']} är inte anslutet."
            )
            return

        result = datasource_store.sync_provider(
            provider, db, payload, days=days, force_full=force_full,
            on_progress=lambda text: _set_sync_job(key, message=text)
        )

        tokens = result.get("tokens") or {}
        if tokens:
            payload.update(tokens)
        datasource_store.save_record(
            conn, user_id, dek, provider, payload,
            connected=bool(record["connected"] or result["success"]),
            last_sync_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S") if result["success"] else None,
            last_sync_count=result["count"] if result["success"] else None,
        )
        _set_sync_job(
            key,
            state="done" if result["success"] else "error",
            message=result["message"],
            count=result["count"],
        )
    except Exception as e:
        logger.error(f"Datasource sync failed for {provider}/user {user_id}: {e}")
        _set_sync_job(key, state="error", message=f"Synkroniseringen misslyckades: {e}")
    finally:
        if conn:
            try:
                conn.close()
            except Exception:
                pass


@app.post("/api/datasources/{provider}/sync")
def sync_datasource(
    provider: str,
    req: Optional[DatasourceSyncRequest] = None,
    session: UserSession = Depends(get_current_session)
):
    """Start a background sync for one data source (poll /sync_status for progress)."""
    require_provider(provider)
    meta = datasource_store.PROVIDERS[provider]
    key = _sync_job_key(session.user_id, provider)

    with datasource_errors("Starten av synkroniseringen"), datasource_session(session) as (_db, conn):
        record = datasource_store.load_record(conn, session.user_id, bytes(session.dek), provider)
        if not datasource_store.has_tokens(provider, record["payload"]):
            raise HTTPException(
                status_code=400,
                detail=f"{meta['name']} är inte anslutet ännu. Anslut kontot innan du synkroniserar."
            )

    with _sync_jobs_lock:
        existing = _sync_jobs.get(key)
        if existing and existing.get("state") == "running":
            return {
                "status": "running",
                "message": existing.get("message", "Synkronisering pågår redan."),
                "provider": provider
            }
        _sync_jobs[key] = {
            "state": "running",
            "provider": provider,
            "message": f"Startar synkronisering med {meta['name']}...",
            "count": 0,
            "started_at": datetime.now().isoformat(timespec="seconds"),
        }

    days = req.days if req and req.days else None
    force_full = bool(req.force_full) if req else False
    thread = threading.Thread(
        target=_run_datasource_sync,
        args=(session.user_id, bytes(session.dek), provider, days, force_full),
        daemon=True,
    )
    thread.start()

    return {
        "status": "running",
        "provider": provider,
        "message": f"Synkronisering med {meta['name']} har startat."
    }


@app.get("/api/datasources/{provider}/sync_status")
def datasource_sync_status(provider: str, session: UserSession = Depends(get_current_session)):
    """Poll the state of the latest sync job for one data source."""
    require_provider(provider)
    with _sync_jobs_lock:
        job = dict(_sync_jobs.get(_sync_job_key(session.user_id, provider)) or {})
    if not job:
        return {"status": "idle", "provider": provider, "message": "", "count": 0}
    return {
        "status": job.get("state", "idle"),
        "provider": provider,
        "message": job.get("message", ""),
        "count": job.get("count", 0),
        "started_at": job.get("started_at"),
    }


# --- STATIC FILES & INDEX HTML ---

static_dir = os.path.join(os.path.dirname(__file__), "static")
if os.path.exists(static_dir):
    app.mount("/static", StaticFiles(directory=static_dir), name="static")


@app.get("/", response_class=HTMLResponse)
def root():
    index_path = os.path.join(static_dir, "index.html")
    if os.path.exists(index_path):
        with open(index_path, "r", encoding="utf-8") as f:
            return HTMLResponse(
                content=f.read(),
                headers={
                    "Cache-Control": "no-cache, no-store, must-revalidate",
                    "Pragma": "no-cache",
                    "Expires": "0"
                }
            )
    return HTMLResponse(content="<h1>HealthChat Web Server Running</h1><p>Static files missing.</p>")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("server:app", host="0.0.0.0", port=8000, reload=True)
