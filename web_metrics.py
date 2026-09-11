"""Calorie-burn computation for the web application.

A port of ``HealthChartsView.update_calorie_card`` plus the backfill the desktop
build never had. The card only ever wrote *today's* row, so the trend chart had
two flaws: a day when nobody opened the app left a permanent gap, and a day
opened once in the morning kept that morning's pro-rated value forever.

The formulas, the step deduction for workouts and the device-BMR projection are
the desktop ones, unchanged.
"""

import json
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

import calorie_calc

logger = logging.getLogger("web_metrics")


def _num(profile: Dict[str, Any], key: str) -> float:
    try:
        return float((profile or {}).get(key) or 0)
    except (TypeError, ValueError):
        return 0.0


def workout_steps_of(activity: Dict[str, Any]) -> int:
    """Steps taken during one logged workout.

    Uses the device value when the activity carries one, otherwise estimates it
    for step-based sports (~1300 steps/km) so those steps can be deducted from
    the day's total instead of being counted twice.
    """
    steps = 0
    raw = activity.get("raw_json")
    if raw:
        try:
            parsed = json.loads(raw) if isinstance(raw, str) else raw
            steps = int(parsed.get("steps") or parsed.get("totalSteps") or 0)
        except Exception:
            steps = 0

    if not steps:
        try:
            steps = int(activity.get("steps") or activity.get("total_steps") or 0)
        except (TypeError, ValueError):
            steps = 0

    if not steps:
        activity_type = str(activity.get("activity_type") or "").lower()
        if any(k in activity_type for k in ("run", "walk", "hike", "löp", "gång", "jogg")):
            try:
                distance = float(activity.get("distance_km") or 0.0)
            except (TypeError, ValueError):
                distance = 0.0
            if distance > 0:
                steps = int(distance * 1300)

    return max(0, steps)


def _workout_totals(act_hist: List[Dict[str, Any]], date: str) -> Dict[str, int]:
    """Calories and steps from the workouts logged on ``date``."""
    calories = 0
    steps = 0
    for activity in act_hist or []:
        if str(activity.get("date") or activity.get("start_time") or "")[:10] != date:
            continue
        try:
            calories += int(float(activity.get("calories") or 0))
        except (TypeError, ValueError):
            pass
        steps += workout_steps_of(activity)
    return {"calories": calories, "steps": steps}


def _device_bmr(day_summary: Dict[str, Any]) -> float:
    raw = day_summary.get("raw_json")
    if not raw:
        try:
            return float(day_summary.get("bmrKilocalories", 0) or 0)
        except (TypeError, ValueError):
            return 0.0
    try:
        parsed = json.loads(raw) if isinstance(raw, str) else raw
        return float(parsed.get("bmrKilocalories", 0) or 0)
    except Exception:
        return 0.0


def _weight_for(profile: Dict[str, Any], body_comp: Optional[Dict[str, Any]]) -> float:
    try:
        weight = float((profile or {}).get("weight_kg") or 0)
    except (TypeError, ValueError):
        weight = 0.0
    if weight <= 0 and body_comp and body_comp.get("weight_kg"):
        try:
            weight = float(body_comp.get("weight_kg") or 0)
        except (TypeError, ValueError):
            weight = 0.0
    return weight


def calorie_snapshot(
    db,
    profile: Dict[str, Any],
    act_hist: List[Dict[str, Any]],
    body_comp: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Today's calorie burn, persisted for the trend chart."""
    today = datetime.now().strftime("%Y-%m-%d")
    weight_kg = _weight_for(profile, body_comp)

    try:
        day_summary = db.get_daily_summary(today) or {}
    except Exception as exc:
        logger.debug("Could not load today's summary: %s", exc)
        day_summary = {}

    try:
        steps = int(day_summary.get("total_steps", 0) or 0)
    except (TypeError, ValueError):
        steps = 0

    # Garmin reports the BMR burned *so far today*, so project it to a full day
    # before the estimator pro-rates it back down.
    device_bmr = _device_bmr(day_summary)
    frac = calorie_calc.day_fraction_elapsed()
    bmr_override = device_bmr / frac if (device_bmr > 0 and frac > 0.05) else device_bmr

    workouts = _workout_totals(act_hist, today)

    result = calorie_calc.estimate_daily_burn(
        weight_kg=weight_kg,
        height_cm=_num(profile, "height_cm"),
        age_years=_num(profile, "age"),
        sex=(profile or {}).get("sex", "male"),
        steps=steps,
        workout_steps=workouts["steps"],
        workout_calories=workouts["calories"],
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
        logger.error("Could not persist today's calorie burn: %s", exc)

    return result


def _weight_on(date: str, measurements: List[Dict[str, Any]], fallback: float) -> float:
    """Body weight as last measured on or before ``date``.

    A year-long trend should not price every day at today's weight, so each day
    uses the most recent weigh-in that had already happened.
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


def backfill_calorie_burn(
    db,
    profile: Dict[str, Any],
    days: int = 365,
    overwrite: bool = False,
) -> Dict[str, Any]:
    """Write a ``calorie_burn`` row for every completed day that has data.

    With ``overwrite=False`` only days that are missing *or* still stored as a
    partial day (``day_fraction < 1``) are written, which makes this cheap
    enough to run on every dashboard load: each day is repaired once and then
    left alone. ``overwrite=True`` recomputes everything, which is what a sync
    wants since it may have brought in new steps or workouts.

    Today is never touched — :func:`calorie_snapshot` owns it, and its value is
    meant to grow as the day elapses.
    """
    today = datetime.now().strftime("%Y-%m-%d")

    summaries = {
        str(row.get("date") or "")[:10]: row
        for row in (db.get_daily_summary_history(days) or [])
        if row.get("date")
    }

    activities = db.get_activities_history(days) or []
    workout_days = {
        str(a.get("date") or a.get("start_time") or "")[:10]
        for a in activities
        if (a.get("date") or a.get("start_time"))
    }

    # date -> how much of that day the stored row covers.
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
    fallback_weight = _weight_for(profile, latest_comp)

    written = 0
    skipped = 0
    for date in sorted(set(summaries) | workout_days):
        if not date or date >= today:
            continue  # today belongs to calorie_snapshot; future dates are noise
        if not overwrite and existing.get(date, 0.0) >= 1.0:
            continue  # already stored as a complete day

        day_summary = summaries.get(date, {})
        try:
            steps = int(day_summary.get("total_steps", 0) or 0)
        except (TypeError, ValueError):
            steps = 0
        bmr_override = _device_bmr(day_summary)
        workouts = _workout_totals(activities, date)

        # Without any of these signals the day holds no evidence at all, and
        # inventing a BMR-only bar would be worse than an honest gap.
        if steps <= 0 and bmr_override <= 0 and workouts["calories"] <= 0:
            skipped += 1
            continue

        weight_kg = _weight_on(date, measurements, fallback_weight)
        result = calorie_calc.estimate_daily_burn(
            weight_kg=weight_kg,
            height_cm=_num(profile, "height_cm"),
            age_years=_num(profile, "age"),
            sex=(profile or {}).get("sex", "male"),
            steps=steps,
            workout_steps=workouts["steps"],
            workout_calories=workouts["calories"],
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
