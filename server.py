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
from typing import Dict, Any, Optional, List
from datetime import datetime, timedelta

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

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("server")

app = FastAPI(
    title="HealthChat Web API",
    description="Secure AI-powered health & fitness analytics platform",
    version="4.1.0"
)

# CORS Middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# In-memory active user sessions keyed by session_id token
_active_sessions: Dict[str, UserSession] = {}
SESSION_COOKIE_NAME = "healthchat_session"


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


class ProfileUpdateRequest(BaseModel):
    sex: Optional[str] = None
    height_cm: Optional[float] = None
    age: Optional[int] = None
    weight_kg: Optional[float] = None


class ChatRequest(BaseModel):
    message: str
    provider: Optional[str] = "openai"
    model: Optional[str] = None


# --- HELPER DEPENDENCIES ---

def get_db() -> GarminDatabase:
    """Instantiate GarminDatabase handler."""
    db = GarminDatabase()
    return db


def get_db_conn(db: GarminDatabase):
    """Get active database connection (MariaDB pool if available, otherwise SQLite fallback connection)."""
    if db.is_mariadb and db.pool:
        return db.get_mariadb_conn()
    return db.get_connection()


def get_current_session(healthchat_session: Optional[str] = Cookie(None)) -> UserSession:
    """Dependency retrieving active UserSession from session cookie."""
    if not healthchat_session or healthchat_session not in _active_sessions:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Ej inloggad eller sessionen har löpt ut."
        )
    return _active_sessions[healthchat_session]


def bind_user_db(session: UserSession) -> GarminDatabase:
    """Create GarminDatabase bound to the authenticated user's DEK."""
    db = GarminDatabase()
    db.set_user_session(session.user_id, session.dek)
    return db


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
        _active_sessions[session_id] = session
        
        response.set_cookie(
            key=SESSION_COOKIE_NAME,
            value=session_id,
            httponly=True,
            samesite="lax",
            max_age=86400 * 30
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
        raise HTTPException(status_code=500, detail=f"Serverfel vid registrering: {e}")
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
        _active_sessions[session_id] = session

        response.set_cookie(
            key=SESSION_COOKIE_NAME,
            value=session_id,
            httponly=True,
            samesite="lax",
            max_age=86400 * 30
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
    if healthchat_session and healthchat_session in _active_sessions:
        session = _active_sessions.pop(healthchat_session)
        session.clear()
        auth.clear_remembered_session(session.email)
    response.delete_cookie(SESSION_COOKIE_NAME)
    return {"status": "success", "message": "Utloggad!"}


@app.get("/api/auth/me")
def get_me(session: UserSession = Depends(get_current_session)):
    return {
        "user_id": session.user_id,
        "email": session.email,
        "profile": session.encrypted_profile or {}
    }


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
    workout_cals_today = sum(
        a.get("calories", 0) for a in activities_hist if str(a.get("date", ""))[:10] == today_str
    )
    
    profile = session.encrypted_profile or {}
    weight = profile.get("weight_kg") or (body_comp_latest.get("weight_kg") if body_comp_latest else 70.0)
    
    burn_estimate = calorie_calc.estimate_daily_burn(
        weight_kg=weight,
        height_cm=profile.get("height_cm"),
        age_years=profile.get("age"),
        sex=profile.get("sex", "male"),
        steps=daily_sum_today.get("total_steps", 0),
        workout_calories=workout_cals_today,
        bmr_override=daily_sum_today.get("bmrKilocalories", 0),
        is_today=True
    )

    return {
        "today_date": today_str,
        "profile": profile,
        "latest_body_comp": body_comp_latest,
        "calorie_burn_today": burn_estimate,
        "sleep_latest": sleep_hist[-1] if sleep_hist else None,
        "bb_latest": bb_hist[-1] if bb_hist else None,
        "stress_latest": stress_hist[-1] if stress_hist else None,
        "hrv_latest": hrv_hist[-1] if hrv_hist else None,
        "activities_recent": activities_hist[:10],
        "history": {
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
async def chat_stream(req: ChatRequest, session: UserSession = Depends(get_current_session)):
    db = bind_user_db(session)
    activities = db.get_activities_history(30)
    sleep = db.get_sleep_history(7)
    
    context_text = f"Användar-ID: {session.user_id}\n"
    if activities:
        context_text += f"Senaste aktiviteter (30d): {len(activities)} st. Senaste: {activities[0].get('activity_name', 'Träning')} ({activities[0].get('distance_km', 0)} km)\n"
    if sleep:
        context_text += f"Senaste sömn: {sleep[-1].get('total_sleep_hours', 0)}h (Kvalitet: {sleep[-1].get('sleep_score', 'N/A')})\n"
    
    prompt = f"Hälsokontext:\n{context_text}\nAnvändarens fråga: {req.message}"
    
    provider = (req.provider or "openai").lower()
    api_key = secret_store.get_secret(f"{provider}_api_key") or ""
    ollama_url = secret_store.get_secret("ollama_base_url") or os.environ.get("OLLAMA_BASE_URL")

    client = AIClient(
        provider=provider,
        api_key=api_key,
        model=req.model,
        ollama_base_url=ollama_url
    )

    async def event_generator():
        try:
            # Execute AI call in thread pool to avoid blocking async looper
            loop = asyncio.get_event_loop()
            response_text = await loop.run_in_executor(None, lambda: client.chat(prompt))
            
            # Stream in chunks for real-time feel
            words = response_text.split(" ")
            for i in range(0, len(words), 3):
                chunk = " ".join(words[i:i+3]) + " "
                yield f"data: {json.dumps({'chunk': chunk})}\n\n"
                await asyncio.sleep(0.03)
            yield f"data: {json.dumps({'done': True})}\n\n"
        except Exception as e:
            logger.error(f"Error streaming AI response: {e}")
            yield f"data: {json.dumps({'error': str(e)})}\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream")


# --- PROFILE ENDPOINTS ---

@app.post("/api/profile/update")
def update_profile(req: ProfileUpdateRequest, session: UserSession = Depends(get_current_session)):
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
            
        auth.update_user_profile(conn, session, current_profile)
        return {"status": "success", "profile": current_profile}
    finally:
        if conn:
            conn.close()


@app.post("/api/profile/change_password")
def change_password(req: ChangePasswordRequest, session: UserSession = Depends(get_current_session)):
    db = bind_user_db(session)
    conn = get_db_conn(db)
    try:
        auth.change_user_password(conn, session.user_id, req.current_password, req.new_password)
        return {"status": "success", "message": "Lösenordet har ändrats!"}
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
            return HTMLResponse(content=f.read())
    return HTMLResponse(content="<h1>HealthChat Web Server Running</h1><p>Static files missing.</p>")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("server:app", host="0.0.0.0", port=8000, reload=True)
