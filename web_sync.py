"""Check-in and historical synchronisation for the web application.

A port of ``perform_unified_checkin``, ``perform_full_historical_sync`` and the
per-source check-ins from the desktop build. The sync itself still runs in
background threads; instead of writing into a Tk status label, progress is
written to the user's workspace and polled by the browser through
``GET /api/sync/status``.
"""

import logging
import threading
from typing import Callable, Dict, List, Optional

import web_metrics

logger = logging.getLogger("web_sync")

SOURCE_LABELS = {
    "garmin": "Garmin",
    "fitbit": "Fitbit",
    "withings": "Withings",
    "strava": "Strava",
}

# Day counts taken from the desktop menus, so a web check-in fetches exactly
# what the desktop one did.
CHECKIN_DAYS = {"garmin": 30, "fitbit": 7, "withings": 365, "strava": 30}
FULL_DAYS = {"garmin": 3650, "fitbit": 365, "withings": 3650, "strava": 3650}


def set_status(workspace, text: str, running: bool = True, done: bool = False) -> None:
    workspace.sync_status = {"text": text, "running": running, "done": done}


def selected_sources(workspace, only: Optional[str] = None) -> List[str]:
    """Connected sources, optionally narrowed to a single one."""
    connected = workspace.connected_sources()
    if only:
        return [only] if connected.get(only) else []
    return [name for name, is_connected in connected.items() if is_connected]


def run_checkin(
    workspace,
    sources: List[str],
    full: bool = False,
    days_range: int = 30,
    on_finished: Optional[Callable[[], None]] = None,
) -> None:
    """Sync the given sources, then recompute the daily calorie burn.

    Runs on the calling thread; the caller decides whether that is a background
    thread (it always is, in the HTTP layer).
    """
    label = " & ".join(SOURCE_LABELS.get(s, s.capitalize()) for s in sources)
    remaining = {"count": len(sources)}
    lock = threading.Lock()
    finished_event = threading.Event()

    def finished(_name: str) -> None:
        with lock:
            remaining["count"] -= 1
            if remaining["count"] > 0:
                return

        # The history is up to date, so (re)compute the daily calorie burn.
        # overwrite=True also repairs days that were frozen at a partial value.
        set_status(workspace, "⏳ Beräknar kaloriförbränning...")
        try:
            web_metrics.backfill_calorie_burn(
                workspace.db(),
                workspace.get_user_profile(),
                days=3650 if full else max(365, days_range),
                overwrite=True,
            )
        except Exception as exc:
            logger.error("Calorie-burn backfill failed after check-in: %s", exc)

        suffix = "Full historik-synk klar" if full else f"Synkning klar ({label})"
        set_status(workspace, f"✅ {suffix}!", running=False, done=True)
        workspace.status = {
            "text": f"✅ Check-in genomförd för {label}! Graferna har uppdaterats.",
            "is_error": False,
        }
        if on_finished:
            on_finished()
        finished_event.set()

    def progress(source: str, unit: str):
        def _report(curr, total, _msg=""):
            set_status(workspace, f"⏳ Synkar {SOURCE_LABELS.get(source, source)} ({curr}/{total} {unit})...")
        return _report

    days = FULL_DAYS if full else CHECKIN_DAYS

    if "garmin" in sources:
        try:
            workspace.garmin_handler.sync_garmin_history(
                days=days["garmin"] if full else max(30, days_range),
                force_full=full,
                on_progress=progress("garmin", "d"),
                on_complete=lambda: finished("garmin"),
            )
        except Exception as exc:
            logger.error("Garmin check-in error: %s", exc)
            finished("garmin")

    if "fitbit" in sources:
        try:
            workspace.fitbit_handler.sync_fitbit_history(
                days=days["fitbit"],
                on_progress=progress("fitbit", "d"),
                on_complete=lambda: finished("fitbit"),
            )
        except Exception as exc:
            logger.error("Fitbit check-in error: %s", exc)
            finished("fitbit")

    if "withings" in sources:
        def withings_worker():
            set_status(workspace, "⏳ Synkar Withings (vikt & kroppssammansättning)...")
            try:
                result = workspace.sync_withings(days=days["withings"], force_full=full)
                set_status(workspace, f"✅ Withings klar ({result.get('count', 0)} mätvärden sparades)")
            except Exception as exc:
                logger.error("Withings check-in error: %s", exc)
            finally:
                finished("withings")

        threading.Thread(target=withings_worker, daemon=True).start()

    if "strava" in sources:
        try:
            workspace.strava_handler.sync_strava_history(
                days=days["strava"],
                on_progress=progress("strava", "pass"),
                on_complete=lambda: finished("strava"),
            )
        except Exception as exc:
            logger.error("Strava check-in error: %s", exc)
            finished("strava")

    # Guard against a handler that never calls back, so the UI cannot hang on
    # "Synkar…" forever.
    if not finished_event.wait(timeout=3600):
        logger.warning("Check-in did not report completion within an hour")
        set_status(workspace, "⚠️ Synken tog för lång tid och avbröts.", running=False, done=True)


def start_checkin(
    workspace,
    only: Optional[str] = None,
    full: bool = False,
    days_range: int = 30,
) -> Dict[str, object]:
    """Kick off a check-in in the background and report what was started."""
    if workspace.sync_status.get("running"):
        return {"started": False, "reason": "busy", "sync_status": workspace.sync_status}

    sources = selected_sources(workspace, only)
    if not sources:
        return {"started": False, "reason": "no_sources", "sources": []}

    label = " & ".join(SOURCE_LABELS.get(s, s.capitalize()) for s in sources)
    set_status(workspace, f"⏳ Synkroniserar {'full historik för ' if full else ''}{label}...")
    workspace.status = {"text": f"📥 Kör Check-in för {label}...", "is_error": False}

    threading.Thread(
        target=run_checkin,
        args=(workspace, sources, full, days_range),
        daemon=True,
    ).start()

    return {"started": True, "sources": sources, "sync_status": workspace.sync_status}
