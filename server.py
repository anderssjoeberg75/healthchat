"""
FastAPI Web Server for HealthChat.
Exposes REST and SSE endpoints for HealthChat Web Application while preserving
the core domain logic, envelope encryption (AES-256-GCM + Argon2id), MariaDB backend,
and multi-provider AI engine.
"""

import os
import sys
import uuid
import json
import logging
import asyncio
import threading
from typing import Dict, Any, Optional, List
from datetime import datetime, timedelta
from contextlib import contextmanager

from fastapi import FastAPI, Request, Response, HTTPException, status, Depends, Cookie, Query
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

def get_cookie_secure() -> bool:
    return os.getenv("COOKIE_SECURE", "1").lower() not in ("0", "false", "no")

_allowed_origins = get_allowed_origins()
_allow_credentials = "*" not in _allowed_origins

# CORS Middleware (S-15)
app.add_middleware(
    CORSMiddleware,
    allow_origins=_allowed_origins,
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




class ChatRequest(BaseModel):
    # AI-leverantören är inte valbar från klienten - all chatt går till den
    # lokala Ollama-servern. Eventuella extrafält från äldre klienter ignoreras.
    message: str


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


def get_current_session(healthchat_session: Optional[str] = Cookie(None)) -> UserSession:
    """Dependency retrieving active UserSession from session cookie."""
    if not healthchat_session:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Ej inloggad eller sessionen har löpt ut."
        )

    session = get_valid_session(healthchat_session)
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
            fresh = load_session_from_db(conn, healthchat_session)
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
def register(req: RegisterRequest, response: Response):
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
            secure=get_cookie_secure(),
            samesite="lax",
            max_age=SESSION_MAX_AGE_SECONDS
        )
        return {
            "status": "success",
            "message": "Konto skapat!",
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
def login(req: LoginRequest, response: Response):
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
            secure=get_cookie_secure(),
            samesite="lax",
            max_age=SESSION_MAX_AGE_SECONDS
        )
        return {
            "status": "success",
            "message": "Inloggningen lyckades!",
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
def logout(response: Response, healthchat_session: Optional[str] = Cookie(None)):
    if healthchat_session:
        session = remove_active_session(healthchat_session)
        if session:
            auth.clear_remembered_session(session.email)
        db = get_db()
        conn = None
        try:
            conn = get_db_conn(db)
            delete_session_from_db(conn, healthchat_session)
        finally:
            if conn:
                try:
                    conn.close()
                except Exception:
                    pass
    response.delete_cookie(
        key=SESSION_COOKIE_NAME,
        httponly=True,
        secure=get_cookie_secure(),
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


def _pick_latest_body_battery(bb_hist: Optional[List[Dict[str, Any]]]) -> Optional[Dict[str, Any]]:
    """Return the most recent Body Battery row that actually carries a value.

    Garmin writes a row for the current day as soon as it is synced, often
    before it has computed any levels. Blindly taking the last row therefore
    blanks out the Recovery card even when the preceding days hold good data,
    so walk backwards to the newest row with a usable metric.
    """
    rows = bb_hist or []
    for entry in reversed(rows):
        if not isinstance(entry, dict):
            continue
        for key in ("highest", "highest_level", "current", "charged"):
            try:
                if float(entry.get(key) or 0) > 0:
                    return {
                        **entry,
                        "highest_level": entry.get("highest") or entry.get("highest_level"),
                    }
            except (TypeError, ValueError):
                continue
    if rows and isinstance(rows[-1], dict):
        return {
            **rows[-1],
            "highest_level": rows[-1].get("highest") or rows[-1].get("highest_level"),
        }
    return None


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
        "bb_latest": _pick_latest_body_battery(bb_hist),
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
    if body_comp.get("weight_kg"):
        context_lines.append(f"Vikt: {body_comp.get('weight_kg')} kg (Fett%: {body_comp.get('fat_ratio_pct', 'N/A')}%)")
    if activities:
        context_lines.append(f"Senaste aktiviteter (30d): {len(activities)} st. Senaste: {activities[0].get('activity_name', 'Träning')} ({activities[0].get('distance_km', 0)} km, {activities[0].get('duration_min', 0)} min)")
    if sleep:
        context_lines.append(f"Senaste sömn: {sleep[-1].get('total_sleep_hours', 0)}h (Score: {sleep[-1].get('sleep_score', 'N/A')})")
    if hrv:
        context_lines.append(f"Senaste HRV: {hrv[-1].get('last_night_avg', 'N/A')} ms (Status: {hrv[-1].get('status', 'N/A')})")
    
    garmin_context = "\n".join(context_lines)
    
    # All AI-chatt körs mot den lokala Ollama-servern. Ingen leverantörsväljare
    # finns i gränssnittet och klienten kan inte styra om anropet.
    ollama_url = secret_store.get_secret("ollama_base_url") or os.environ.get("OLLAMA_BASE_URL")
    ollama_model = secret_store.get_secret("ollama_model") or os.environ.get("OLLAMA_MODEL")

    client = AIClient(
        provider="ollama",
        api_key="",
        model=ollama_model,
        ollama_base_url=ollama_url
    )

    # Restore prior conversation history for this active session
    if healthchat_session and healthchat_session in _session_chat_histories:
        client.conversation_history = list(_session_chat_histories[healthchat_session])

    async def event_generator():
        try:
            # Execute AI call in thread pool to avoid blocking async looper
            loop = asyncio.get_event_loop()
            response_text = await loop.run_in_executor(
                None, lambda: client.chat(req.message, garmin_context=garmin_context)
            )

            # Persist updated conversation history
            if healthchat_session:
                _session_chat_histories[healthchat_session] = list(client.conversation_history)
            
            # SSE Protocol contract with static/app.js:
            # - data: {"chunk": "<text>"} for streamed text pieces
            # - data: {"done": true} to signal successful completion
            # - data: {"error": "<message>"} to signal failure
            words = response_text.split(" ")
            for i in range(0, len(words), 3):
                chunk = " ".join(words[i:i+3]) + " "
                yield f"data: {json.dumps({'chunk': chunk}, ensure_ascii=False)}\n\n"
                await asyncio.sleep(0.03)
            yield f"data: {json.dumps({'done': True})}\n\n"
        except Exception as e:
            logger.error(f"Error streaming AI response: {e}")
            yield f"data: {json.dumps({'error': str(e)}, ensure_ascii=False)}\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream")


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
    req: Optional[DeleteAccountRequest] = None,
    healthchat_session: Optional[str] = Cookie(None),
    session: UserSession = Depends(get_current_session)
):
    db = bind_user_db(session)
    conn = get_db_conn(db)
    try:
        if conn:
            pw = req.current_password if req else None
            auth.delete_user_account(conn, session.user_id, current_password=pw)
        if healthchat_session:
            remove_active_session(healthchat_session)
            delete_session_from_db(conn, healthchat_session)
        if response:
            response.delete_cookie(
                key=SESSION_COOKIE_NAME,
                httponly=True,
                secure=get_cookie_secure(),
                samesite="lax"
            )
        return {"status": "success", "message": "Konto raderat!"}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    finally:
        if conn:
            conn.close()


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
