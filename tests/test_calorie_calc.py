"""Tests for calorie_calc — the approximate daily calorie-burn estimator.

Fully offline and deterministic: time-of-day pro-rating is exercised with an
explicit ``at_time`` so no test depends on the wall clock.
"""

from datetime import datetime

import pytest

import calorie_calc


# --- BMR formulas --------------------------------------------------------------

def test_mifflin_st_jeor_male():
    # 10*80 + 6.25*180 - 5*40 + 5 = 800 + 1125 - 200 + 5 = 1730
    bmr = calorie_calc.mifflin_st_jeor_bmr(80, 180, 40, "male")
    assert bmr == pytest.approx(1730.0)


def test_mifflin_st_jeor_female_offset():
    male = calorie_calc.mifflin_st_jeor_bmr(70, 165, 35, "male")
    female = calorie_calc.mifflin_st_jeor_bmr(70, 165, 35, "female")
    # Only the sex constant differs: +5 vs -161 -> 166 kcal apart.
    assert male - female == pytest.approx(166.0)


def test_mifflin_zero_weight_is_zero():
    assert calorie_calc.mifflin_st_jeor_bmr(0, 180, 40, "male") == 0.0


def test_simple_bmr_scales_with_weight_and_sex():
    assert calorie_calc.simple_bmr(80, "male") == pytest.approx(1920.0)
    assert calorie_calc.simple_bmr(80, "female") == pytest.approx(1760.0)
    assert calorie_calc.simple_bmr(0) == 0.0


# --- Steps ---------------------------------------------------------------------

def test_calories_per_step_scales_with_weight():
    assert calorie_calc.calories_per_step(70) == pytest.approx(0.04)
    assert calorie_calc.calories_per_step(140) == pytest.approx(0.08)


def test_calories_per_step_defaults_when_no_weight():
    # Falls back to a 70 kg reference rather than dividing by zero.
    assert calorie_calc.calories_per_step(0) == pytest.approx(0.04)


def test_step_burn_never_negative():
    assert calorie_calc.step_burn(-500, 80) == 0


# --- Day fraction --------------------------------------------------------------

def test_day_fraction_midday():
    at = datetime(2026, 9, 4, 12, 0, 0)
    assert calorie_calc.day_fraction_elapsed(at) == pytest.approx(0.5)


def test_day_fraction_bounds():
    assert calorie_calc.day_fraction_elapsed(datetime(2026, 9, 4, 0, 0, 0)) == pytest.approx(0.0)
    assert calorie_calc.day_fraction_elapsed(datetime(2026, 9, 4, 23, 59, 0)) < 1.0


# --- Full estimate -------------------------------------------------------------

def test_estimate_prorates_resting_for_today():
    noon = datetime(2026, 9, 4, 12, 0, 0)
    result = calorie_calc.estimate_daily_burn(
        weight_kg=80, height_cm=180, age_years=40, sex="male",
        steps=0, workout_calories=0, is_today=True, at_time=noon,
    )
    # Half a day of a 1730 kcal BMR.
    assert result["bmr_full"] == 1730
    assert result["resting_burn"] == pytest.approx(865, abs=1)
    assert result["bmr_source"] == "mifflin"
    assert result["total_burn"] == result["resting_burn"]


def test_estimate_full_day_for_past_day():
    result = calorie_calc.estimate_daily_burn(
        weight_kg=80, height_cm=180, age_years=40, sex="male",
        steps=0, workout_calories=0, is_today=False,
    )
    assert result["day_fraction"] == 1.0
    assert result["resting_burn"] == 1730


def test_estimate_combines_all_three_components():
    result = calorie_calc.estimate_daily_burn(
        weight_kg=80, height_cm=180, age_years=40, sex="male",
        steps=10000, workout_calories=500, is_today=False,
    )
    # steps: 10000 * 0.04 * (80/70) ~= 457
    assert result["steps"] == 10000
    assert result["steps_burn"] == pytest.approx(457, abs=1)
    assert result["workout_burn"] == 500
    assert result["total_burn"] == (
        result["resting_burn"] + result["steps_burn"] + result["workout_burn"]
    )


def test_bmr_override_takes_precedence():
    result = calorie_calc.estimate_daily_burn(
        weight_kg=80, height_cm=180, age_years=40, sex="male",
        bmr_override=1600, is_today=False,
    )
    assert result["bmr_source"] == "device"
    assert result["bmr_full"] == 1600
    assert result["resting_burn"] == 1600


def test_simple_fallback_when_profile_incomplete():
    # No height/age -> simple 24*kg estimate for a male.
    result = calorie_calc.estimate_daily_burn(
        weight_kg=80, sex="male", is_today=False,
    )
    assert result["bmr_source"] == "simple"
    assert result["bmr_full"] == 1920


def test_estimate_with_no_data_is_zero():
    result = calorie_calc.estimate_daily_burn(is_today=False)
    assert result["total_burn"] == 0
    assert result["bmr_full"] == 0
