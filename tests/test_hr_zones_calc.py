"""Tests for hr_zones_calc — Heart Rate Zones and Maffetone MAF calculation."""

import pytest

import hr_zones_calc


def test_calculate_maf_hr():
    # 40 years old -> 180 - 40 = 140 bpm, range 130-140 bpm
    maf = hr_zones_calc.calculate_maf_hr(40)
    assert maf["base_maf"] == 140
    assert maf["maf_target"] == 140
    assert maf["maf_min"] == 130
    assert maf["maf_max"] == 140
    assert maf["range_str"] == "130 – 140 bpm"
    assert maf["warmup_range_str"] == "120 – 130 bpm"


def test_calculate_maf_hr_with_categories():
    # Category A: -10 bpm
    maf_a = hr_zones_calc.calculate_maf_hr(40, category="A")
    assert maf_a["adjustment"] == -10
    assert maf_a["maf_target"] == 130
    assert "Kategori A" in maf_a["category_desc"]

    # Category B: -5 bpm
    maf_b = hr_zones_calc.calculate_maf_hr(40, category="B")
    assert maf_b["adjustment"] == -5
    assert maf_b["maf_target"] == 135
    assert "Kategori B" in maf_b["category_desc"]

    # Category C: 0 bpm
    maf_c = hr_zones_calc.calculate_maf_hr(40, category="C")
    assert maf_c["adjustment"] == 0
    assert maf_c["maf_target"] == 140
    assert "Kategori C" in maf_c["category_desc"]

    # Category D: +5 bpm
    maf_d = hr_zones_calc.calculate_maf_hr(40, category="D")
    assert maf_d["adjustment"] == 5
    assert maf_d["maf_target"] == 145
    assert "Kategori D" in maf_d["category_desc"]


def test_calculate_maf_hr_auto_detection():
    # Injury / illness flag -> Category B (-5 bpm)
    maf_inj = hr_zones_calc.calculate_maf_hr(40, has_injury_or_illness=True)
    assert maf_inj["adjustment"] == -5
    assert maf_inj["maf_target"] == 135

    # 3 years training without injury -> Category D (+5 bpm)
    maf_exp = hr_zones_calc.calculate_maf_hr(40, training_years=3.0, has_injury_or_illness=False)
    assert maf_exp["adjustment"] == 5
    assert maf_exp["maf_target"] == 145


def test_calculate_hr_zones_karvonen():
    # Age 40, Rest HR 60, Max HR formula = 180. HRR = 120.
    # Zone 1 (50-60% HRR): 60 + 0.5*120=120 to 60 + 0.6*120=132
    # Zone 2 (60-70% HRR): 60 + 0.6*120=132 to 60 + 0.7*120=144
    res = hr_zones_calc.calculate_hr_zones(age=40, resting_hr=60)
    assert res["max_hr"] == 180
    assert res["resting_hr"] == 60
    assert res["hrr"] == 120
    assert len(res["zones"]) == 5

    z1 = res["zones"][0]
    assert z1["bpm_low"] == 120
    assert z1["bpm_high"] == 132

    z2 = res["zones"][1]
    assert z2["bpm_low"] == 132
    assert z2["bpm_high"] == 144

    z5 = res["zones"][4]
    assert z5["bpm_low"] == 168
    assert z5["bpm_high"] == 180


def test_calculate_hr_zones_max_hr_override():
    # User max HR override = 190, Rest HR = 50. HRR = 140.
    res = hr_zones_calc.calculate_hr_zones(age=30, resting_hr=50, max_hr_override=190)
    assert res["max_hr"] == 190
    assert res["max_source"] == "user"
    assert res["hrr"] == 140

