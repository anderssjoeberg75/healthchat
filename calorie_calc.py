"""
Approximate daily calorie-burn estimation for HealthChat Desktop.

The goal here is a simple, *transparent* benchmark of how many calories the
user has burned "so far today" — not clinical accuracy. The estimate combines
three easy-to-understand components:

  1. Resting burn (BMR) - what the body burns at rest, pro-rated to the part
                          of the day that has already elapsed.
  2. Step burn          - active calories from the steps walked so far.
  3. Workout burn       - calories from logged training sessions.

Because steps, workouts and resting metabolism overlap in reality, the sum is
deliberately a rough figure ("ungefärligt") meant only as a trend marker.

This module is intentionally free of any UI or database dependency so it can be
unit-tested in isolation.
"""

from datetime import datetime
from typing import Optional


def mifflin_st_jeor_bmr(weight_kg: float, height_cm: float, age_years: float, sex: str) -> float:
    """Full-day basal metabolic rate (kcal / 24h) via the Mifflin-St Jeor equation.

    Men:   BMR = 10*kg + 6.25*cm - 5*age + 5
    Women: BMR = 10*kg + 6.25*cm - 5*age - 161
    """
    if not weight_kg or weight_kg <= 0:
        return 0.0
    sex_offset = 5.0 if str(sex).lower().startswith("m") else -161.0
    return 10.0 * float(weight_kg) + 6.25 * float(height_cm or 0) - 5.0 * float(age_years or 0) + sex_offset


def simple_bmr(weight_kg: float, sex: str = "male") -> float:
    """Rough BMR fallback (~1 kcal per kg per hour) for when height/age are unknown."""
    if not weight_kg or weight_kg <= 0:
        return 0.0
    factor = 24.0 if str(sex).lower().startswith("m") else 22.0
    return factor * float(weight_kg)


def calories_per_step(weight_kg: float) -> float:
    """Approximate active kcal burned per step, scaled to body weight.

    ~0.04 kcal/step is a common estimate for a ~70 kg person; scale linearly.
    """
    w = float(weight_kg) if (weight_kg and weight_kg > 0) else 70.0
    return 0.04 * (w / 70.0)


def step_burn(steps: int, weight_kg: float) -> float:
    """Calories burned from `steps`, scaled to body weight."""
    return max(0, int(steps or 0)) * calories_per_step(weight_kg)


def day_fraction_elapsed(at_time: Optional[datetime] = None) -> float:
    """Fraction (0..1) of the current day that has elapsed at `at_time` (default: now)."""
    now = at_time or datetime.now()
    minutes = now.hour * 60 + now.minute + now.second / 60.0
    return max(0.0, min(1.0, minutes / 1440.0))


def estimate_daily_burn(
    *,
    weight_kg: float = 0.0,
    height_cm: float = 0.0,
    age_years: float = 0,
    sex: str = "male",
    steps: int = 0,
    workout_calories: float = 0.0,
    bmr_override: float = 0.0,
    is_today: bool = True,
    at_time: Optional[datetime] = None,
) -> dict:
    """Estimate the approximate calories burned for a single day.

    Parameters
    ----------
    weight_kg, height_cm, age_years, sex:
        Used to compute BMR when no device value is supplied.
    steps:
        Steps walked so far on the day.
    workout_calories:
        Sum of calories from logged workouts on the day.
    bmr_override:
        If > 0 (e.g. Garmin's ``bmrKilocalories``), this real device BMR is used
        as the full-day resting burn instead of the estimate.
    is_today:
        When True the resting portion is pro-rated to the elapsed part of the day
        (so the value grows through the day). For a completed past day the full
        BMR is counted.

    Returns a dict with the breakdown and the ``total_burn`` (all rounded ints,
    except ``day_fraction``).
    """
    # --- Full-day resting burn (BMR) -------------------------------------
    if bmr_override and bmr_override > 0:
        bmr_full = float(bmr_override)
        bmr_source = "device"
    elif height_cm and age_years:
        bmr_full = mifflin_st_jeor_bmr(weight_kg, height_cm, age_years, sex)
        bmr_source = "mifflin"
    else:
        bmr_full = simple_bmr(weight_kg, sex)
        bmr_source = "simple"
    bmr_full = max(0.0, bmr_full)

    frac = day_fraction_elapsed(at_time) if is_today else 1.0
    resting_burn = bmr_full * frac

    steps_burn_val = step_burn(steps, weight_kg)
    workout_burn = max(0.0, float(workout_calories or 0.0))
    total = resting_burn + steps_burn_val + workout_burn

    return {
        "bmr_full": round(bmr_full),
        "bmr_source": bmr_source,
        "day_fraction": round(frac, 4),
        "resting_burn": round(resting_burn),
        "steps": int(steps or 0),
        "steps_burn": round(steps_burn_val),
        "workout_burn": round(workout_burn),
        "total_burn": round(total),
    }
