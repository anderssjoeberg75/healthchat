"""Garmin connection and data synchronisation (Check-in / full history).

Long-running syncs run in background threads exactly as they did on the desktop.
Instead of writing into a Tk status label, progress is written to the user's
workspace and polled by the browser through ``GET /api/sync/status``.
"""

import logging
import sys
import tempfile
import threading
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel

from .. import config
from ..deps import current_workspace
from ..workspace import Workspace

sys.path.insert(0, str(config.PROJECT_ROOT))
from withings_handler import WithingsDataHandler  # noqa: E402

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api", tags=["sync"])


class MfaCode(BaseModel):
    code: str


class SyncRequest(BaseModel):
    days: int = 30
    full: bool = False


def _set_sync(workspace: Workspace, text: str, running: bool = True, done: bool = False) -> None:
    workspace.sync_status = {"text": text, "running": running, "done": done}


@router.get("/status")
def get_status(workspace: Workspace = Depends(current_workspace)):
    # Reconnect using stored Garmin tokens so a page reload keeps the session.
    if not workspace.authenticated:
        workspace.restore_garmin_session()
    return {
        "authenticated": workspace.authenticated,
        "mfa_required": workspace.mfa_required,
        "status": workspace.status,
        "sync_status": workspace.sync_status,
        "sources": workspace.connected_sources(),
    }


@router.post("/garmin/connect")
def connect_garmin(workspace: Workspace = Depends(current_workspace)):
    """Authenticate against Garmin Connect (the old '▶ Connect to Garmin' button)."""
    if not workspace.get_current_ai_key() or not workspace.config.get("garmin_email") \
            or not workspace.config.get("garmin_password"):
        raise HTTPException(
            status_code=400,
            detail="Fyll i Garmin-uppgifter och API-nyckel under Inställningar innan du ansluter.",
        )

    if not workspace.initialize_ai_client():
        raise HTTPException(status_code=400, detail="Failed to initialize AI client. Please check your settings.")

    try:
        handler = workspace.build_garmin_handler()
        result = handler.authenticate()
    except Exception as exc:
        logger.error("Garmin authentication failed: %s", exc)
        workspace.status = {"text": f"❌ {exc}", "is_error": True}
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    if result.get("success"):
        workspace.authenticated = True
        workspace.mfa_required = False
        workspace.status = {"text": "✅ Connected to Garmin Connect!", "is_error": False}
        workspace.add_message(
            "System",
            "Connected to Garmin Connect! You can now ask questions about your fitness data.",
            "system",
        )
        threading.Thread(target=workspace.sync_withings, daemon=True).start()
        return {"authenticated": True, "mfa_required": False, "status": workspace.status}

    if result.get("mfa_required"):
        workspace.mfa_required = True
        workspace.authenticated = False
        workspace.status = {"text": "🔐 MFA Required: Enter your 6-digit code", "is_error": False}
        return {"authenticated": False, "mfa_required": True, "status": workspace.status}

    error = result.get("error", "Unknown Garmin authentication error")
    workspace.status = {"text": f"❌ {error}", "is_error": True}
    raise HTTPException(status_code=401, detail=error)


@router.post("/garmin/mfa")
def submit_mfa(payload: MfaCode, workspace: Workspace = Depends(current_workspace)):
    code = (payload.code or "").strip()
    if len(code) != 6:
        raise HTTPException(status_code=400, detail="Please enter a valid 6-digit MFA code")
    if not workspace.garmin_handler:
        raise HTTPException(status_code=400, detail="Starta anslutningen till Garmin först.")

    try:
        result = workspace.garmin_handler.submit_mfa(code)
    except Exception as exc:
        workspace.status = {"text": f"❌ {exc}", "is_error": True}
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    if result.get("success"):
        workspace.authenticated = True
        workspace.mfa_required = False
        workspace.status = {"text": "✅ Connected to Garmin Connect!", "is_error": False}
        workspace.add_message(
            "System",
            "Connected to Garmin Connect! You can now ask questions about your fitness data.",
            "system",
        )
        return {"authenticated": True, "status": workspace.status}

    error = result.get("error", "Unknown MFA error")
    workspace.status = {"text": f"❌ {error}", "is_error": True}
    raise HTTPException(status_code=401, detail=error)


def _run_checkin(workspace: Workspace, days: int, full: bool) -> None:
    """Sync every connected source, mirroring perform_unified_checkin."""
    sources = workspace.connected_sources()
    names = [name.capitalize() for name, connected in sources.items() if connected]
    source_str = " & ".join(names)
    remaining = {"count": len(names)}
    lock = threading.Lock()

    def finished(_name: str) -> None:
        with lock:
            remaining["count"] -= 1
            if remaining["count"] <= 0:
                _set_sync(workspace, f"✅ Synkning klar ({source_str})!", running=False, done=True)
                workspace.status = {
                    "text": f"✅ Check-in genomförd för {source_str}! Graferna har uppdaterats.",
                    "is_error": False,
                }

    if sources["garmin"]:
        def garmin_progress(curr, total, _msg):
            label = "full historik" if full else "d"
            _set_sync(workspace, f"⏳ Synkar Garmin ({curr}/{total} {label})...")

        try:
            workspace.garmin_handler.sync_garmin_history(
                days=3650 if full else max(30, days),
                force_full=full,
                on_progress=garmin_progress,
                on_complete=lambda: finished("Garmin"),
            )
        except Exception as exc:
            logger.error("Garmin check-in error: %s", exc)
            finished("Garmin")

    if sources["fitbit"]:
        def fitbit_progress(curr, total, _msg):
            _set_sync(workspace, f"⏳ Synkar Fitbit ({curr}/{total} d)...")

        try:
            workspace.fitbit_handler.sync_fitbit_history(
                days=365 if full else 7,
                on_progress=fitbit_progress,
                on_complete=lambda: finished("Fitbit"),
            )
        except Exception as exc:
            logger.error("Fitbit check-in error: %s", exc)
            finished("Fitbit")

    if sources["withings"]:
        def withings_worker():
            _set_sync(workspace, "⏳ Synkar Withings (vikt & kroppssammansättning)...")
            try:
                result = workspace.sync_withings(days=3650 if full else 365, force_full=full)
                _set_sync(workspace, f"✅ Withings klar ({result.get('count', 0)} mätvärden sparades)")
            except Exception as exc:
                logger.error("Withings check-in error: %s", exc)
            finally:
                finished("Withings")

        threading.Thread(target=withings_worker, daemon=True).start()

    if sources["strava"]:
        def strava_progress(curr, total, _msg):
            _set_sync(workspace, f"⏳ Synkar Strava ({curr}/{total} pass)...")

        try:
            workspace.strava_handler.sync_strava_history(
                days=365 if full else 30,
                on_progress=strava_progress,
                on_complete=lambda: finished("Strava"),
            )
        except Exception as exc:
            logger.error("Strava check-in error: %s", exc)
            finished("Strava")


@router.post("/checkin")
def checkin(payload: Optional[SyncRequest] = None, workspace: Workspace = Depends(current_workspace)):
    """Run Check-in (or a full historical sync) across all connected sources."""
    payload = payload or SyncRequest()
    if workspace.sync_status.get("running"):
        return {"started": False, "sync_status": workspace.sync_status}

    sources = workspace.connected_sources()
    names = [name.capitalize() for name, connected in sources.items() if connected]
    if not names:
        raise HTTPException(
            status_code=400,
            detail="Du är inte ansluten till någon hälsokälla än.\n\n"
                   "Anslut till Garmin Connect, Fitbit eller Withings via Inställningar först.",
        )

    source_str = " & ".join(names)
    _set_sync(workspace, f"⏳ Synkroniserar {source_str}...")
    workspace.status = {"text": f"📥 Kör Check-in för {source_str}...", "is_error": False}
    threading.Thread(target=_run_checkin, args=(workspace, payload.days, payload.full), daemon=True).start()
    return {"started": True, "sources": names, "sync_status": workspace.sync_status}


@router.get("/sync/status")
def sync_status(workspace: Workspace = Depends(current_workspace)):
    return {"sync_status": workspace.sync_status, "status": workspace.status}


@router.post("/refresh")
def refresh(workspace: Workspace = Depends(current_workspace)):
    """Refresh Garmin data (the old 'Refresh' button)."""
    if not (workspace.garmin_handler and workspace.authenticated):
        raise HTTPException(status_code=400, detail="Anslut till Garmin först.")
    try:
        summary = workspace.garmin_handler.get_user_summary()
        workspace.status = {"text": "✅ Data refreshed successfully!", "is_error": False}
        return {"ok": True, "summary": summary}
    except Exception as exc:
        workspace.status = {"text": f"❌ Error refreshing data: {exc}", "is_error": True}
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.post("/import/{source}")
async def import_export_file(source: str, file: UploadFile = File(...),
                             workspace: Workspace = Depends(current_workspace)):
    """Import an official export file from Fitbit, Strava or Withings.

    The desktop build read the file straight off the user's disk; here the
    browser uploads it and the server hands the temporary copy to the same
    importer.
    """
    if source not in ("fitbit", "strava", "withings"):
        raise HTTPException(status_code=404, detail="Okänd källa.")

    suffix = Path(file.filename or "").suffix or ".dat"
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
    try:
        tmp.write(await file.read())
        tmp.close()

        if source == "fitbit":
            result = workspace.fitbit_handler.import_fitbit_export_file(tmp.name)
        elif source == "strava":
            result = workspace.strava_handler.import_strava_export_file(tmp.name)
        else:
            handler = workspace.withings_handler() or WithingsDataHandler(db=workspace.db)
            result = handler.import_withings_export_file(tmp.name)
    except Exception as exc:
        logger.error("%s import failed: %s", source, exc)
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    finally:
        Path(tmp.name).unlink(missing_ok=True)

    return {"ok": True, "source": source, "result": result}
