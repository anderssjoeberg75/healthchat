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
import tempfile
import threading
from pathlib import Path
from typing import Dict, Any, Optional, List
from datetime import datetime, timedelta

from fastapi import (
    FastAPI, Request, Response, HTTPException, status, Depends, Cookie, Query, File, UploadFile,
)
from fastapi.responses import HTMLResponse, StreamingResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, EmailStr

import garmin_db
from garmin_db import GarminDatabase
import auth
from auth import UserSession, mask_email
import crypto
import ai_client
from ai_client import AIClient
import calorie_calc
import hr_zones_calc
from withings_handler import WithingsDataHandler

# Web layer: per-user runtime state and the features ported from the desktop UI.
import web_workspace
import web_chat
import web_export
import web_metrics
import web_sync
import web_dbcompat

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
    """The account database: the MariaDB pool when available, else SQLite.

    ``auth`` speaks pymysql, so the SQLite fallback is wrapped in a small
    compatibility layer (:mod:`web_dbcompat`). Without it the application could
    not even log a user in when the MariaDB host was unreachable.
    """
    if db.is_mariadb and db.pool:
        return db.get_mariadb_conn()
    return web_dbcompat.connect(Path(db.db_path))


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
    finally:
        if conn:
            conn.close()


@app.post("/api/auth/login")
def login(req: LoginRequest, response: Response):
    db = get_db()
    conn = get_db_conn(db)
    try:
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
    finally:
        if conn:
            conn.close()


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

    today_str = datetime.now().strftime("%Y-%m-%d")
    ws = web_workspace.get_workspace(session)
    profile = ws.get_user_profile()

    # Today's estimate, stored so it becomes part of the trend; then repair any
    # completed day that is missing or was frozen at a partial value.
    burn_estimate = web_metrics.calorie_snapshot(db, profile, activities_hist, body_comp_latest)
    try:
        web_metrics.backfill_calorie_burn(db, profile, days=max(365, days))
    except Exception as exc:
        logger.error("Calorie-burn backfill failed: %s", exc)
    calorie_burn_hist = db.get_calorie_burn_history(days)

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

@app.post("/api/ai/chat")
async def chat_stream(req: ChatRequest, session: UserSession = Depends(get_current_session)):
    """Ask the coach a question and stream the answer back.

    The context, the provider selection and the conversation memory are the
    desktop build's (see :mod:`web_chat`); only the delivery is streamed.
    """
    ws = web_workspace.get_workspace(session)

    if req.provider:
        # An explicit provider from the UI overrides the stored default for this turn.
        ws.load_settings()
        if ws.settings.get("ai_provider") != req.provider:
            ws.update_settings({"ai_provider": req.provider})

    if not ws.get_current_ai_key():
        raise HTTPException(
            status_code=400,
            detail="Ange en API-nyckel för din AI-leverantör under Inställningar först.",
        )

    message = (req.message or "").strip()
    if not message:
        raise HTTPException(status_code=400, detail="Skriv ett meddelande först.")

    ws.add_message("Du", message, "user")

    async def event_generator():
        try:
            loop = asyncio.get_event_loop()
            entry = await loop.run_in_executor(None, lambda: web_chat.process_message(ws, message))
            response_text = entry.get("message", "")

            # Stream in chunks for real-time feel
            words = response_text.split(" ")
            for i in range(0, len(words), 3):
                chunk = " ".join(words[i:i+3]) + " "
                yield f"data: {json.dumps({'chunk': chunk})}\n\n"
                await asyncio.sleep(0.03)
            yield f"data: {json.dumps({'done': True})}\n\n"
        except Exception as e:
            logger.error(f"Error streaming AI response: {e}")
            ws.add_message("System", f"Tyvärr, ett fel uppstod: {e}", "system")
            yield f"data: {json.dumps({'error': str(e)})}\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream")


# --- PROFILE ENDPOINTS ---

@app.post("/api/user/profile")
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
        web_workspace.get_workspace(session).refresh_session(session)
        return {"status": "success", "profile": current_profile}
    finally:
        if conn:
            conn.close()


@app.post("/api/user/password")
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


# --- WORKSPACE-BACKED ENDPOINTS ---------------------------------------------
# Everything below restores functionality the desktop build had. Each endpoint
# drives the same domain code the Tk UI drove; only the transport differs.


class SettingsUpdateRequest(BaseModel):
    values: Dict[str, Any]


class MfaRequest(BaseModel):
    code: str


class CheckinRequest(BaseModel):
    source: Optional[str] = None
    full: bool = False
    days: int = 30


class PromptRequest(BaseModel):
    name: str
    prompt: str


class QuickQuestionsRequest(BaseModel):
    questions: List[str]


class ChatNameRequest(BaseModel):
    name: str


class ChatMessageRequest(BaseModel):
    message: str


class ExportRequest(BaseModel):
    format: str = "txt"
    include_timestamp: bool = True
    include_system: bool = False


def get_workspace_dep(session: UserSession = Depends(get_current_session)) -> web_workspace.Workspace:
    """The calling user's workspace (settings, handlers, AI client, chat)."""
    return web_workspace.get_workspace(session)


# --- SETTINGS ---------------------------------------------------------------

@app.get("/api/settings")
def get_settings(ws: web_workspace.Workspace = Depends(get_workspace_dep)):
    """Settings for the browser. Secrets are reported as set/unset only."""
    return {
        "config": ws.public_settings(),
        "profile": ws.get_user_profile(),
        "providers": AIClient.get_available_providers(),
        "sources": ws.connected_sources(),
        "redirect_base": base_url(),
    }


@app.post("/api/settings")
def save_settings(req: SettingsUpdateRequest, ws: web_workspace.Workspace = Depends(get_workspace_dep)):
    ws.update_settings(req.values or {})
    return {"status": "success", "config": ws.public_settings()}


@app.get("/api/settings/models")
def list_models(provider: str, ws: web_workspace.Workspace = Depends(get_workspace_dep)):
    """Live model list for a provider, falling back to the built-in list."""
    ws.load_settings()
    api_key = ws.settings.get(f"{provider}_api_key", "") or ""
    base = ws.settings.get("ollama_base_url", "") if provider == "ollama" else ""
    try:
        models = AIClient.fetch_models(provider, api_key=api_key, base_url=base)
    except Exception as exc:
        logger.info("Falling back to the static model list for %s: %s", provider, exc)
        models = AIClient.get_provider_models(provider)
    return {"provider": provider, "models": models}


# --- CONNECTION STATUS & GARMIN --------------------------------------------

@app.get("/api/status")
def connection_status(ws: web_workspace.Workspace = Depends(get_workspace_dep)):
    if not ws.authenticated:
        ws.restore_garmin_session()
    return {
        "authenticated": ws.authenticated,
        "mfa_required": ws.mfa_required,
        "status": ws.status,
        "sync_status": ws.sync_status,
        "sources": ws.connected_sources(),
    }


@app.post("/api/garmin/connect")
def garmin_connect(ws: web_workspace.Workspace = Depends(get_workspace_dep)):
    """Authenticate against Garmin Connect (the desktop '▶ Anslut' button)."""
    ws.load_settings()
    if not ws.settings.get("garmin_email") or not ws.settings.get("garmin_password"):
        raise HTTPException(
            status_code=400,
            detail="Fyll i dina Garmin-uppgifter under Inställningar innan du ansluter.",
        )
    if not ws.get_current_ai_key():
        raise HTTPException(
            status_code=400,
            detail="Ange en API-nyckel för din AI-leverantör under Inställningar först.",
        )

    if not ws.initialize_ai_client():
        raise HTTPException(status_code=400, detail="Kunde inte initiera AI-klienten. Kontrollera inställningarna.")

    try:
        result = ws.build_garmin_handler().authenticate()
    except Exception as exc:
        logger.error("Garmin authentication failed: %s", exc)
        ws.status = {"text": f"❌ {exc}", "is_error": True}
        raise HTTPException(status_code=502, detail=str(exc))

    if result.get("success"):
        ws.authenticated = True
        ws.mfa_required = False
        ws.status = {"text": "✅ Ansluten till Garmin Connect!", "is_error": False}
        ws.add_message("System", "Ansluten till Garmin Connect! Du kan nu ställa frågor om dina träningsdata.", "system")
        threading.Thread(target=ws.sync_withings, daemon=True).start()
        return {"authenticated": True, "mfa_required": False, "status": ws.status}

    if result.get("mfa_required"):
        ws.mfa_required = True
        ws.authenticated = False
        ws.status = {"text": "🔐 MFA krävs: ange din 6-siffriga kod", "is_error": False}
        return {"authenticated": False, "mfa_required": True, "status": ws.status}

    error = result.get("error", "Okänt fel vid Garmin-inloggning")
    ws.status = {"text": f"❌ {error}", "is_error": True}
    raise HTTPException(status_code=401, detail=error)


@app.post("/api/garmin/mfa")
def garmin_mfa(req: MfaRequest, ws: web_workspace.Workspace = Depends(get_workspace_dep)):
    code = (req.code or "").strip()
    if len(code) != 6:
        raise HTTPException(status_code=400, detail="Ange en giltig 6-siffrig MFA-kod.")
    if not ws.garmin_handler:
        raise HTTPException(status_code=400, detail="Starta anslutningen till Garmin först.")

    try:
        result = ws.garmin_handler.submit_mfa(code)
    except Exception as exc:
        ws.status = {"text": f"❌ {exc}", "is_error": True}
        raise HTTPException(status_code=502, detail=str(exc))

    if result.get("success"):
        ws.authenticated = True
        ws.mfa_required = False
        ws.status = {"text": "✅ Ansluten till Garmin Connect!", "is_error": False}
        ws.add_message("System", "Ansluten till Garmin Connect! Du kan nu ställa frågor om dina träningsdata.", "system")
        return {"authenticated": True, "status": ws.status}

    error = result.get("error", "Okänt MFA-fel")
    ws.status = {"text": f"❌ {error}", "is_error": True}
    raise HTTPException(status_code=401, detail=error)


# --- CHECK-IN & SYNC --------------------------------------------------------

@app.post("/api/checkin")
def checkin(req: Optional[CheckinRequest] = None, ws: web_workspace.Workspace = Depends(get_workspace_dep)):
    """Check-in across every connected source, or one named source."""
    req = req or CheckinRequest()
    if req.source and req.source not in web_sync.SOURCE_LABELS:
        raise HTTPException(status_code=404, detail="Okänd källa.")

    result = web_sync.start_checkin(ws, only=req.source, full=req.full, days_range=req.days)
    if result.get("reason") == "no_sources":
        raise HTTPException(
            status_code=400,
            detail="Du är inte ansluten till någon hälsokälla än.\n\n"
                   "Anslut till Garmin Connect, Fitbit, Withings eller Strava först.",
        )
    return result


@app.get("/api/sync/status")
def sync_status(ws: web_workspace.Workspace = Depends(get_workspace_dep)):
    return {"sync_status": ws.sync_status, "status": ws.status}


@app.post("/api/refresh")
def refresh_data(ws: web_workspace.Workspace = Depends(get_workspace_dep)):
    """Refresh Garmin data (the desktop 'Refresh' button)."""
    if not (ws.garmin_handler and ws.authenticated):
        raise HTTPException(status_code=400, detail="Anslut till Garmin först.")
    try:
        summary = ws.garmin_handler.get_user_summary()
        ws.status = {"text": "✅ Data uppdaterad!", "is_error": False}
        return {"status": "success", "summary": summary}
    except Exception as exc:
        ws.status = {"text": f"❌ Kunde inte uppdatera: {exc}", "is_error": True}
        raise HTTPException(status_code=502, detail=str(exc))


@app.post("/api/import/{source}")
async def import_export_file(
    source: str,
    file: UploadFile = File(...),
    ws: web_workspace.Workspace = Depends(get_workspace_dep),
):
    """Import an official export file from Fitbit, Strava or Withings."""
    if source not in ("fitbit", "strava", "withings"):
        raise HTTPException(status_code=404, detail="Okänd källa.")

    suffix = Path(file.filename or "").suffix or ".dat"
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
    try:
        tmp.write(await file.read())
        tmp.close()

        if source == "fitbit":
            result = ws.fitbit_handler.import_fitbit_export_file(tmp.name)
        elif source == "strava":
            result = ws.strava_handler.import_strava_export_file(tmp.name)
        else:
            handler = ws.withings_handler() or WithingsDataHandler(db=ws.db())
            result = handler.import_withings_export_file(tmp.name)
    except Exception as exc:
        logger.error("%s import failed: %s", source, exc)
        raise HTTPException(status_code=400, detail=str(exc))
    finally:
        Path(tmp.name).unlink(missing_ok=True)

    return {"status": "success", "source": source, "result": result}


# --- OAUTH FOR FITBIT / STRAVA / WITHINGS -----------------------------------

OAUTH_SERVICES = ("fitbit", "strava", "withings")

# One-shot CSRF states: state token -> user id.
_oauth_states: Dict[str, int] = {}


def base_url() -> str:
    return os.environ.get("HEALTHCHAT_BASE_URL", "http://localhost:8000").rstrip("/")


def oauth_redirect_uri(service: str) -> str:
    return f"{base_url()}/oauth/{service}/callback"


def _oauth_result_page(title: str, message: str, colour: str) -> HTMLResponse:
    """The same confirmation page the desktop's local callback server showed."""
    return HTMLResponse(
        f"""
        <html>
        <head><meta charset="utf-8"><title>HealthChat</title></head>
        <body style="font-family: Segoe UI, sans-serif; text-align: center; padding-top: 50px; background: #F3F4F6;">
            <div style="background: white; max-width: 500px; margin: 0 auto; padding: 40px; border-radius: 12px; box-shadow: 0 4px 12px rgba(0,0,0,0.1);">
                <h2 style="color: {colour}; margin-bottom: 10px;">{title}</h2>
                <p style="color: #4B5563; font-size: 16px;">{message}</p>
                <p style="color: #6B7280; font-size: 14px;"><a href="/" style="color:#0078D4;">Tillbaka till HealthChat</a></p>
            </div>
        </body>
        </html>
        """
    )


@app.get("/api/connect/{service}/url")
def connect_url(service: str, ws: web_workspace.Workspace = Depends(get_workspace_dep)):
    """Build the provider's authorization URL for this user."""
    if service not in OAUTH_SERVICES:
        raise HTTPException(status_code=404, detail="Okänd tjänst.")

    ws.load_settings()
    client_id = (ws.settings.get(f"{service}_client_id") or "").strip()
    if not client_id:
        raise HTTPException(status_code=400, detail="Fyll i ditt Client ID först innan du klickar på inloggning.")

    state = uuid.uuid4().hex
    _oauth_states[state] = ws.user_id
    redirect = oauth_redirect_uri(service)

    if service == "fitbit":
        url = ws.fitbit_handler.get_auth_url(client_id, redirect) + f"&state={state}"
    elif service == "strava":
        url = ws.strava_handler.get_auth_url(client_id, redirect) + f"&state={state}"
    else:
        url = WithingsDataHandler.get_auth_url(client_id, redirect).replace("state=withings_state", f"state={state}")

    return {"url": url, "redirect_uri": redirect}


@app.get("/oauth/{service}/callback")
def oauth_callback(service: str, request: Request, healthchat_session: Optional[str] = Cookie(None)):
    if service not in OAUTH_SERVICES:
        raise HTTPException(status_code=404, detail="Okänd tjänst.")

    code = request.query_params.get("code")
    state = request.query_params.get("state", "")
    if not code:
        return _oauth_result_page("Ingen kod mottogs", "Auktoriseringen avbröts.", "#EF4444")

    # Resolve the user from the one-shot state, falling back to the session cookie.
    user_id = _oauth_states.pop(state, None)
    session = _active_sessions.get(healthchat_session) if healthchat_session else None
    if user_id is None and session is None:
        return _oauth_result_page("Sessionen har gått ut", "Logga in i HealthChat och försök igen.", "#EF4444")
    if session is None or (user_id is not None and session.user_id != user_id):
        session = next((s for s in _active_sessions.values() if s.user_id == user_id), session)
    if session is None:
        return _oauth_result_page("Sessionen har gått ut", "Logga in i HealthChat och försök igen.", "#EF4444")

    ws = web_workspace.get_workspace(session)
    ws.load_settings()
    client_id = (ws.settings.get(f"{service}_client_id") or "").strip()
    client_secret = (ws.settings.get(f"{service}_client_secret") or "").strip()

    try:
        if service == "fitbit":
            ws.fitbit_handler.exchange_code_for_token(code, client_id, client_secret, oauth_redirect_uri("fitbit"))
            return _oauth_result_page("✅ Fitbit Ansluten!", "Ditt Fitbit-konto har anslutits till HealthChat.", "#10B981")

        if service == "strava":
            ws.strava_handler.exchange_code_for_token(code, client_id, client_secret, oauth_redirect_uri("strava"))
            return _oauth_result_page("✅ Strava Ansluten!", "Ditt Strava-konto har anslutits till HealthChat.", "#FC4C02")

        handler = WithingsDataHandler(client_id=client_id, client_secret=client_secret, refresh_token="", db=ws.db())
        result = handler.exchange_code_for_token(code, client_id, client_secret, oauth_redirect_uri("withings"))
        ws.settings["withings_access_token"] = result.get("access_token", "")
        ws.settings["withings_refresh_token"] = result.get("refresh_token", "")
        ws.save_settings()
        return _oauth_result_page("✅ Withings Ansluten!", "Ditt Withings-konto har anslutits till HealthChat.", "#10B981")

    except Exception as exc:
        logger.error("%s OAuth exchange failed: %s", service, exc)
        return _oauth_result_page(f"❌ Kunde inte ansluta till {service.capitalize()}", str(exc), "#EF4444")


@app.post("/api/connect/{service}/disconnect")
def disconnect_service(service: str, ws: web_workspace.Workspace = Depends(get_workspace_dep)):
    """Forget the stored tokens for one source."""
    if service not in OAUTH_SERVICES:
        raise HTTPException(status_code=404, detail="Okänd tjänst.")

    if service == "withings":
        ws.settings["withings_access_token"] = ""
        ws.settings["withings_refresh_token"] = ""
        ws.save_settings()
    else:
        handler = ws.fitbit_handler if service == "fitbit" else ws.strava_handler
        handler.access_token = ""
        handler.refresh_token = ""
        token_file = getattr(handler, "token_file", None)
        if token_file and token_file.exists():
            token_file.unlink()

    return {"status": "success", "sources": ws.connected_sources()}


# --- QUICK QUESTIONS & SAVED PROMPTS ---------------------------------------

@app.get("/api/quick-questions")
def get_quick_questions(ws: web_workspace.Workspace = Depends(get_workspace_dep)):
    return {"questions": ws.load_quick_questions()}


@app.post("/api/quick-questions")
def set_quick_questions(req: QuickQuestionsRequest, ws: web_workspace.Workspace = Depends(get_workspace_dep)):
    return {"questions": ws.save_quick_questions(req.questions)}


@app.get("/api/prompts")
def get_prompts(ws: web_workspace.Workspace = Depends(get_workspace_dep)):
    return {"prompts": ws.load_saved_prompts()}


@app.post("/api/prompts")
def add_prompt(req: PromptRequest, ws: web_workspace.Workspace = Depends(get_workspace_dep)):
    prompts = ws.load_saved_prompts()
    prompts.append({"name": req.name.strip() or "Prompt", "prompt": req.prompt})
    ws.write_saved_prompts(prompts)
    return {"prompts": prompts}


@app.put("/api/prompts/{index}")
def update_prompt(index: int, req: PromptRequest, ws: web_workspace.Workspace = Depends(get_workspace_dep)):
    prompts = ws.load_saved_prompts()
    if not 0 <= index < len(prompts):
        raise HTTPException(status_code=404, detail="Prompten finns inte.")
    prompts[index] = {"name": req.name.strip() or "Prompt", "prompt": req.prompt}
    ws.write_saved_prompts(prompts)
    return {"prompts": prompts}


@app.delete("/api/prompts/{index}")
def delete_prompt(index: int, ws: web_workspace.Workspace = Depends(get_workspace_dep)):
    prompts = ws.load_saved_prompts()
    if not 0 <= index < len(prompts):
        raise HTTPException(status_code=404, detail="Prompten finns inte.")
    prompts.pop(index)
    ws.write_saved_prompts(prompts)
    return {"prompts": prompts}


# --- CONVERSATION, HISTORY, SEARCH & EXPORT --------------------------------

@app.get("/api/chat")
def get_chat(ws: web_workspace.Workspace = Depends(get_workspace_dep)):
    return {"messages": ws.current_chat_history, "authenticated": ws.authenticated}


@app.post("/api/chat")
def post_chat(req: ChatMessageRequest, ws: web_workspace.Workspace = Depends(get_workspace_dep)):
    """Ask the coach a question, with the same context the desktop built."""
    message = (req.message or "").strip()
    if not message:
        raise HTTPException(status_code=400, detail="Skriv ett meddelande först.")
    if not ws.get_current_ai_key():
        raise HTTPException(status_code=400, detail="Ange en API-nyckel för din AI-leverantör under Inställningar först.")

    ws.add_message("Du", message, "user")
    try:
        answer = web_chat.process_message(ws, message)
    except Exception as exc:
        logger.error("Chat failed: %s", exc)
        answer = ws.add_message("System", f"Tyvärr, ett fel uppstod: {exc}", "system")
    return {"reply": answer, "messages": ws.current_chat_history}


@app.post("/api/chat/reset")
def reset_chat(ws: web_workspace.Workspace = Depends(get_workspace_dep)):
    ws.reset_chat()
    return {"messages": ws.current_chat_history}


@app.get("/api/chats")
def list_chats(ws: web_workspace.Workspace = Depends(get_workspace_dep)):
    return {"chats": ws.list_saved_chats()}


@app.post("/api/chats")
def save_chat(req: ChatNameRequest, ws: web_workspace.Workspace = Depends(get_workspace_dep)):
    if not ws.current_chat_history:
        raise HTTPException(status_code=400, detail="Det finns ingen chatt att spara än!")
    return {"chat": ws.save_current_chat(req.name)}


@app.get("/api/chats/{chat_id}")
def read_chat(chat_id: str, ws: web_workspace.Workspace = Depends(get_workspace_dep)):
    chat = ws.read_saved_chat(chat_id)
    if chat is None:
        raise HTTPException(status_code=404, detail="Chatten finns inte.")
    return {"chat": chat}


@app.post("/api/chats/{chat_id}/load")
def load_chat(chat_id: str, ws: web_workspace.Workspace = Depends(get_workspace_dep)):
    chat = ws.read_saved_chat(chat_id)
    if chat is None:
        raise HTTPException(status_code=404, detail="Chatten finns inte.")
    ws.current_chat_history = list(chat.get("messages", []))
    return {"messages": ws.current_chat_history}


@app.put("/api/chats/{chat_id}")
def rename_chat(chat_id: str, req: ChatNameRequest, ws: web_workspace.Workspace = Depends(get_workspace_dep)):
    if not ws.rename_saved_chat(chat_id, req.name):
        raise HTTPException(status_code=404, detail="Chatten finns inte.")
    return {"chats": ws.list_saved_chats()}


@app.delete("/api/chats/{chat_id}")
def delete_chat(chat_id: str, ws: web_workspace.Workspace = Depends(get_workspace_dep)):
    if not ws.delete_saved_chat(chat_id):
        raise HTTPException(status_code=404, detail="Chatten finns inte.")
    return {"chats": ws.list_saved_chats()}


@app.get("/api/search")
def search_chats(q: str, ws: web_workspace.Workspace = Depends(get_workspace_dep)):
    return {"results": ws.search_chats(q)}


@app.post("/api/export")
def export_conversation(req: ExportRequest, ws: web_workspace.Workspace = Depends(get_workspace_dep)):
    fmt = (req.format or "txt").lower()
    exporter = web_export.EXPORTERS.get(fmt)
    if exporter is None:
        raise HTTPException(status_code=400, detail="Formatet stöds inte (txt, pdf eller docx).")
    if not ws.current_chat_history:
        raise HTTPException(status_code=400, detail="Det finns ingen chatt att exportera än!")

    try:
        content = exporter(ws.current_chat_history, req.include_timestamp, req.include_system)
    except ImportError as exc:
        # Same fallback as the desktop when reportlab/python-docx is missing.
        logger.warning("Export dependency missing for %s: %s", fmt, exc)
        content = web_export.export_txt(ws.current_chat_history, req.include_timestamp, req.include_system)
        fmt = "txt"

    filename = f"healthchat_rapport_{datetime.now().strftime('%Y%m%d_%H%M%S')}.{fmt}"
    return Response(
        content=content,
        media_type=web_export.MEDIA_TYPES[fmt],
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@app.get("/api/hr-zones")
def get_hr_zones(ws: web_workspace.Workspace = Depends(get_workspace_dep)):
    """Karvonen/MAF heart-rate zones for the logged-in user."""
    db = ws.db()
    profile = ws.get_user_profile()

    # Resting HR: the most recent value the device has reported.
    resting_hr = 0
    for row in reversed(db.get_daily_summary_history(90) or []):
        try:
            candidate = int(row.get("resting_hr") or 0)
        except (TypeError, ValueError):
            continue
        if candidate > 0:
            resting_hr = candidate
            break

    zones = hr_zones_calc.calculate_hr_zones(
        age=profile.get("age") or 40,
        resting_hr=resting_hr or 60,
        max_hr_override=profile.get("max_hr") or 0,
        sex=profile.get("sex", "male"),
    )
    return {"zones": zones, "resting_hr": resting_hr, "profile": profile}


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
