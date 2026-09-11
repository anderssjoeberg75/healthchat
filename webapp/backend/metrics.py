"""Dashboard card values and the activity table.

A direct port of ``HealthChartsView.update_dashboard_cards``,
``update_calorie_card`` and ``populate_activities_table`` from the desktop
build: the same formulas and the same texts, returned as JSON instead of being
written into Tk labels.
"""

import json
import logging
import sys
from datetime import datetime
from typing import Any, Dict, List, Optional

from . import config

sys.path.insert(0, str(config.PROJECT_ROOT))

import calorie_calc  # noqa: E402

logger = logging.getLogger(__name__)


def _fmt_thousands(n: float) -> str:
    return f"{int(n):,}".replace(",", " ")


def dashboard_cards(
    db,
    profile: Dict[str, Any],
    sleep_hist: List[Dict[str, Any]],
    bb_hist: List[Dict[str, Any]],
    stress_hist: List[Dict[str, Any]],
    act_hist: List[Dict[str, Any]],
    body_comp: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    """Values for the four text cards plus today's calorie-burn card."""
    # 1. Running & Fitness Index
    fit_score = 70.0
    if act_hist:
        valid_runs = [a for a in act_hist if (a.get("distance_km") or 0) > 0 and (a.get("avg_hr") or 0) > 0]
        if valid_runs:
            ratios = [
                ((a.get("distance_km") or 0) / (a.get("duration_min") or 1)) * (180.0 / (a.get("avg_hr") or 140))
                for a in valid_runs
            ]
            avg_ratio = sum(ratios) / len(ratios)
            fit_score = min(99.0, max(45.0, 50.0 + (avg_ratio * 15.0)))

    latest_bb = bb_hist[-1] if bb_hist else {}
    charged = latest_bb.get("charged", 85) or 85
    rec_val = latest_bb.get("highest", 90) or 90

    cards: Dict[str, Any] = {
        "fitness": {
            "value": f"{fit_score:.1f}",
            "subtitle": f"Beräknat från {len(act_hist)} träningspass & pulszoner",
        },
        "training_status": {
            "value": "⚡ Produktiv Träning",
            "subtitle": f"Base Fitness: 68 | Fatigue: 42 | Load: +{charged}",
        },
        "recovery": {
            "value": f"{rec_val}%",
            "subtitle": "Återhämtad och redo för träning!",
            "positive": rec_val > 70,
        },
    }

    # 4. Weight card
    if body_comp and body_comp.get("weight_kg"):
        cards["weight"] = {
            "value": f"{body_comp.get('weight_kg'):.1f} kg",
            "subtitle": (
                f"Fett: {body_comp.get('fat_ratio_pct', 0.0):.1f}% | "
                f"Muskelmassa: {body_comp.get('muscle_mass_kg', 0.0):.1f} kg"
            ),
            "source": f"Källa: {str(body_comp.get('source') or 'Withings').title()} ({body_comp.get('date')})",
        }
    else:
        cards["weight"] = {"empty": "Ingen vikt registrerad"}

    cards["calories"] = calorie_card(db, profile, body_comp, act_hist)
    return cards


def calorie_card(
    db,
    profile: Dict[str, Any],
    body_comp: Optional[Dict[str, Any]],
    act_hist: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """Estimate today's calorie burn and persist it for the trend chart."""
    today = datetime.now().strftime("%Y-%m-%d")
    profile = profile or {}

    # Body weight: prefer an explicit profile weight, else the latest measurement.
    try:
        weight_kg = float(profile.get("weight_kg") or 0)
    except (TypeError, ValueError):
        weight_kg = 0.0
    if weight_kg <= 0 and body_comp and body_comp.get("weight_kg"):
        try:
            weight_kg = float(body_comp.get("weight_kg") or 0)
        except (TypeError, ValueError):
            weight_kg = 0.0

    day_summary: Dict[str, Any] = {}
    try:
        day_summary = db.get_daily_summary(today) or {}
    except Exception as exc:
        logger.debug("Could not load daily summary for calorie card: %s", exc)

    steps = int(day_summary.get("total_steps", 0) or 0)
    bmr_override = 0.0
    raw = day_summary.get("raw_json")
    if raw:
        try:
            bmr_override = float(json.loads(raw).get("bmrKilocalories", 0) or 0)
        except Exception:
            bmr_override = 0.0

    workout_cal = 0
    for activity in act_hist or []:
        if str(activity.get("date") or activity.get("start_time") or "")[:10] == today:
            try:
                workout_cal += int(float(activity.get("calories") or 0))
            except (TypeError, ValueError):
                pass

    def _num(key: str) -> float:
        try:
            return float(profile.get(key) or 0)
        except (TypeError, ValueError):
            return 0.0

    result = calorie_calc.estimate_daily_burn(
        weight_kg=weight_kg,
        height_cm=_num("height_cm"),
        age_years=_num("age"),
        sex=profile.get("sex", "male"),
        steps=steps,
        workout_calories=workout_cal,
        bmr_override=bmr_override,
        is_today=True,
    )

    try:
        db.upsert_calorie_burn(
            today,
            total_burn=result["total_burn"],
            resting_burn=result["resting_burn"],
            steps_burn=result["steps_burn"],
            workout_burn=result["workout_burn"],
            bmr_full=result["bmr_full"],
            steps=result["steps"],
            weight_kg=weight_kg,
            day_fraction=result["day_fraction"],
            bmr_source=result["bmr_source"],
        )
    except Exception as exc:
        logger.error("Could not persist calorie burn: %s", exc)

    if result["total_burn"] <= 0:
        return {
            "empty": "Ingen data ännu",
            "empty_help": "Synka Garmin och ange din profil\n(längd, ålder, kön) i Inställningar\nför en uppskattning.",
        }

    return {
        "total": f"🔥 {_fmt_thousands(result['total_burn'])} kcal",
        "subtitle": "Förbränt hittills idag (ungefärligt)",
        "resting": f"🛌 Vila (BMR): {_fmt_thousands(result['resting_burn'])} kcal",
        "steps": f"👟 Steg: {_fmt_thousands(result['steps_burn'])} kcal ({_fmt_thousands(result['steps'])} steg)",
        "workout": f"🏋️ Träning: {_fmt_thousands(result['workout_burn'])} kcal",
        "note": {
            "device": "Vilo-BMR från Garmin",
            "mifflin": "Vilo-BMR beräknad från din profil",
            "simple": "Vilo-BMR grovt uppskattad (ange profil för bättre värde)",
        }.get(result["bmr_source"], ""),
    }


def _profile_weight(profile: Dict[str, Any]) -> float:
    try:
        weight = float((profile or {}).get("weight_kg") or 0)
    except (TypeError, ValueError):
        weight = 0.0
    return weight if weight > 0 else 0.0


def _weight_on(date: str, measurements: List[Dict[str, Any]], fallback: float) -> float:
    """Body weight as last measured on or before ``date``.

    A trend chart covering a year should not price every day at today's weight,
    so each day uses the most recent weigh-in that had already happened.
    """
    weight = 0.0
    for row in measurements:  # ascending by date
        if str(row.get("date") or "")[:10] > date:
            break
        try:
            candidate = float(row.get("weight_kg") or 0)
        except (TypeError, ValueError):
            continue
        if candidate > 0:
            weight = candidate
    return weight or fallback


def _device_bmr(day_summary: Dict[str, Any]) -> float:
    raw = day_summary.get("raw_json")
    if not raw:
        return 0.0
    try:
        return float(json.loads(raw).get("bmrKilocalories", 0) or 0)
    except Exception:
        return 0.0


def backfill_calorie_burn(
    db,
    profile: Dict[str, Any],
    days: int = 365,
    overwrite: bool = False,
) -> Dict[str, Any]:
    """Write a ``calorie_burn`` row for every completed day that has data.

    Only :func:`calorie_card` used to write to this table, and only for *today*,
    so the trend chart had two flaws: a day when nobody opened the app left a
    permanent gap, and a day when it was opened once in the morning kept that
    morning's partial value forever. This walks the synced history and computes
    each past day in full (``is_today=False``, so the whole day's resting burn
    counts instead of a pro-rated slice).

    With ``overwrite=False`` only days that are missing *or* still stored as a
    partial day (``day_fraction < 1``) are written, which makes this cheap
    enough to run on every dashboard load: each day is repaired once and then
    left alone. ``overwrite=True`` recomputes every day, which is what a sync
    wants since it may have brought in new steps or workouts for days that
    already looked complete.

    Today is never touched — :func:`calorie_card` owns it, and its value is
    meant to grow as the day elapses.
    """
    today = datetime.now().strftime("%Y-%m-%d")

    summaries = {
        str(row.get("date") or "")[:10]: row
        for row in (db.get_daily_summary_history(days) or [])
        if row.get("date")
    }

    workouts: Dict[str, float] = {}
    for activity in db.get_activities_history(days) or []:
        date = str(activity.get("date") or activity.get("start_time") or "")[:10]
        if not date:
            continue
        try:
            workouts[date] = workouts.get(date, 0.0) + float(activity.get("calories") or 0)
        except (TypeError, ValueError):
            continue

    # date -> how much of that day the stored row covers. A completed day left
    # at a fraction below 1 was frozen mid-day and needs recomputing.
    existing: Dict[str, float] = {}
    for row in db.get_calorie_burn_history(days) or []:
        date = str(row.get("date") or "")[:10]
        if not date:
            continue
        try:
            existing[date] = float(row.get("day_fraction") or 0)
        except (TypeError, ValueError):
            existing[date] = 0.0

    measurements = db.get_body_composition_history(days=days) or []
    latest_comp = db.get_latest_body_composition() or {}
    try:
        latest_weight = float(latest_comp.get("weight_kg") or 0)
    except (TypeError, ValueError):
        latest_weight = 0.0
    fallback_weight = _profile_weight(profile) or latest_weight

    def _num(key: str) -> float:
        try:
            return float((profile or {}).get(key) or 0)
        except (TypeError, ValueError):
            return 0.0

    written = 0
    skipped = 0
    for date in sorted(set(summaries) | set(workouts)):
        if date >= today:
            continue  # today belongs to calorie_card; future dates are noise
        if not overwrite and existing.get(date, 0.0) >= 1.0:
            continue  # already stored as a complete day

        day_summary = summaries.get(date, {})
        steps = int(day_summary.get("total_steps", 0) or 0)
        bmr_override = _device_bmr(day_summary)
        workout_cal = workouts.get(date, 0.0)

        # Without any of these three signals the day holds no evidence at all,
        # and inventing a BMR-only bar would be worse than an honest gap.
        if steps <= 0 and bmr_override <= 0 and workout_cal <= 0:
            skipped += 1
            continue

        weight_kg = _weight_on(date, measurements, fallback_weight)
        result = calorie_calc.estimate_daily_burn(
            weight_kg=weight_kg,
            height_cm=_num("height_cm"),
            age_years=_num("age"),
            sex=(profile or {}).get("sex", "male"),
            steps=steps,
            workout_calories=workout_cal,
            bmr_override=bmr_override,
            is_today=False,
        )

        try:
            db.upsert_calorie_burn(
                date,
                total_burn=result["total_burn"],
                resting_burn=result["resting_burn"],
                steps_burn=result["steps_burn"],
                workout_burn=result["workout_burn"],
                bmr_full=result["bmr_full"],
                steps=result["steps"],
                weight_kg=weight_kg,
                day_fraction=result["day_fraction"],
                bmr_source=result["bmr_source"],
            )
            written += 1
        except Exception as exc:
            logger.error("Could not backfill calorie burn for %s: %s", date, exc)

    if written:
        logger.info("Backfilled calorie burn for %s day(s) (overwrite=%s)", written, overwrite)
    return {"written": written, "skipped": skipped, "days": days}


def activity_rows(act_hist: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Rows for the activities table, newest first, with source detection."""
    if not act_hist:
        return []

    rows = []
    for act in sorted(act_hist, key=lambda x: str(x.get("date") or x.get("start_time") or ""), reverse=True):
        src_raw = str(act.get("source") or "").strip()
        if not src_raw or src_raw.lower() == "garmin":
            raw = act.get("raw_json") or {}
            if isinstance(raw, str):
                try:
                    raw = json.loads(raw)
                except Exception:
                    raw = {}
            if isinstance(raw, dict) and (
                "athlete" in raw
                or "sport_type" in raw
                or "map" in raw
                or "kilojoules" in raw
                or "resource_state" in raw
                or "Activity ID" in raw
            ):
                source = "Strava"
            elif isinstance(raw, dict) and ("logId" in raw or "dateOfSleep" in raw):
                source = "Fitbit"
            else:
                source = src_raw.capitalize() if src_raw else "Garmin"
        else:
            source = src_raw.capitalize()

        rows.append(
            {
                "date": str(act.get("date") or act.get("start_time") or "N/A")[:10],
                "source": source,
                "name": str(act.get("activity_name") or "Workout"),
                "type": str(act.get("activity_type") or "General"),
                "distance": f"{float(act.get('distance_km') or 0.0):.2f}",
                "duration": f"{float(act.get('duration_min') or 0.0):.1f}",
                "calories": int(float(act.get("calories") or 0)),
                "hr": int(float(act.get("avg_hr") or 0)),
            }
        )
    return rows
