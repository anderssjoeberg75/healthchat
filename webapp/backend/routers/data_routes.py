"""Dashboard data and the rendered chart images."""

import logging

from fastapi import APIRouter, Depends, Query, Response

from .. import charts, metrics
from ..deps import current_workspace
from ..workspace import Workspace

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api", tags=["data"])

PNG_HEADERS = {"Cache-Control": "no-store"}


def _history(workspace: Workspace, days: int):
    """The same six queries ``refresh_all_views`` ran on every refresh."""
    return {
        "daily_summary": workspace.db.get_daily_summary_history(days),
        "sleep": workspace.db.get_sleep_history(days),
        "body_battery": workspace.db.get_body_battery_history(days),
        "stress": workspace.db.get_stress_history(days),
        "hrv": workspace.db.get_hrv_history(days),
        "activities_range": workspace.db.get_activities_history(days),
        "activities_full": workspace.db.get_activities_history(max(365, days)),
        "body_comp": workspace.db.get_latest_body_composition(),
    }


@router.get("/dashboard")
def dashboard(days: int = Query(30, ge=1, le=3650), workspace: Workspace = Depends(current_workspace)):
    data = _history(workspace, days)

    # Fill in past days that never got a calorie-burn row (the card only ever
    # writes today's). Missing days only, so this normally writes nothing.
    profile = workspace.get_user_profile()
    try:
        metrics.backfill_calorie_burn(workspace.db, profile, days=max(365, days))
    except Exception as exc:
        logger.error("Calorie-burn backfill failed: %s", exc)

    cards = metrics.dashboard_cards(
        workspace.db,
        profile,
        data["sleep"],
        data["body_battery"],
        data["stress"],
        data["activities_full"],
        data["body_comp"],
    )
    return {
        "days": days,
        "cards": cards,
        "activities": metrics.activity_rows(data["activities_range"]),
        "sources": workspace.connected_sources(),
        "status": workspace.status,
        "sync_status": workspace.sync_status,
    }


@router.get("/charts/weekly.png")
def chart_weekly(days: int = Query(30, ge=1, le=3650), workspace: Workspace = Depends(current_workspace)):
    png = charts.render_weekly_activity(workspace.db.get_activities_history(days))
    return Response(content=png, media_type="image/png", headers=PNG_HEADERS)


@router.get("/charts/trends.png")
def chart_trends(days: int = Query(30, ge=1, le=3650), workspace: Workspace = Depends(current_workspace)):
    png = charts.render_bb_sleep_stress(
        workspace.db.get_sleep_history(days),
        workspace.db.get_body_battery_history(days),
        workspace.db.get_stress_history(days),
    )
    return Response(content=png, media_type="image/png", headers=PNG_HEADERS)


@router.get("/charts/evolab.png")
def chart_evolab(days: int = Query(30, ge=1, le=3650), workspace: Workspace = Depends(current_workspace)):
    data = _history(workspace, days)
    png = charts.render_evolab(
        workspace.db,
        days,
        data["sleep"],
        data["body_battery"],
        data["stress"],
        data["hrv"],
        data["activities_full"],
        data["body_comp"],
        data["daily_summary"],
    )
    return Response(content=png, media_type="image/png", headers=PNG_HEADERS)
