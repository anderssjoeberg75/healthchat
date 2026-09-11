"""
Heart rate zone and Maffetone (MAF 180) calculation engine for HealthChat.

Calculates:
  1. Karvonen Heart Rate Reserve (HRR) zones (Zones 1-5).
  2. Dr. Philip Maffetone's MAF 180 aerobic training threshold and target zone.
"""

from typing import Dict, Optional


def calculate_maf_hr(
    age: float,
    adjustment: int = 0,
    category: Optional[str] = None,
    training_years: Optional[float] = None,
    has_injury_or_illness: bool = False,
    is_beginner: bool = False,
) -> Dict:
    """Calculate Dr. Philip Maffetone's MAF 180 heart rate target, categories & guidance.

    The Maffetone 180 Formula:
      Base MAF = 180 - age

    Category Adjustments:
      - Category A (-10 bpm): Recovering from major illness (heart surgery, stroke), chronic illness, or severe overtraining.
      - Category B (-5 bpm) : Injured, frequent colds/illness, asthma/allergies, beginner or returning from injury.
      - Category C (0 bpm)  : Training regularly for up to 2 years without major injury/illness.
      - Category D (+5 bpm) : Training consistently for > 2 years without injury/illness with continuous progress.

    Parameters
    ----------
    age:
        User's age in years.
    adjustment:
        Optional manual adjustment in bpm (-10, -5, 0, +5).
    category:
        Optional category string ('A', 'B', 'C', 'D').
    training_years:
        Years of continuous training.
    has_injury_or_illness:
        True if currently injured or frequently sick.
    is_beginner:
        True if new to training or training irregularly.

    Returns a dict with complete MAF calculation metrics, category description, and MAF test protocol.
    """
    valid_age = float(age) if (age and float(age) > 0) else 40.0
    base_maf = 180.0 - valid_age

    # Determine category adjustment
    adj = int(adjustment or 0)
    cat_code = category.upper() if (category and isinstance(category, str)) else None
    cat_desc = "Standard (Kategori C, 0 bpm)"

    if cat_code == 'A' or cat_code == 'MAJOR_ILLNESS':
        adj = -10
        cat_desc = "Kategori A (-10 bpm): Återhämtning från allvarlig sjukdom/operation eller kroniska besvär"
    elif cat_code == 'B' or cat_code == 'INJURED_BEGINNER':
        adj = -5
        cat_desc = "Kategori B (-5 bpm): Nyligen skadad, ofta förkyld/sjuk, allergi eller nybörjare/oregelbunden träning"
    elif cat_code == 'C' or cat_code == 'REGULAR':
        adj = 0
        cat_desc = "Kategori C (0 bpm): Tränat regelbundet upp till 2 år utan större skador eller sjukdom"
    elif cat_code == 'D' or cat_code == 'EXPERIENCED':
        adj = 5
        cat_desc = "Kategori D (+5 bpm): Tränat regelbundet i mer än 2 år utan skador och med kontinuerlig utveckling"
    elif has_injury_or_illness or is_beginner:
        adj = -5
        cat_desc = "Kategori B (-5 bpm): Indikerad skada/sjukdom eller nybörjarstatus"
    elif training_years is not None and float(training_years) >= 2.0 and not has_injury_or_illness:
        adj = 5
        cat_desc = "Kategori D (+5 bpm): Indikerad kontinuerlig träning i över 2 år utan skador"
    elif adj != 0:
        cat_desc = f"Användarjustering ({adj:+d} bpm)"

    target = max(40.0, base_maf + adj)
    min_maf = max(30.0, target - 10.0)
    warmup_low = max(30.0, target - 20.0)

    maf_test_steps = [
        "1. Förberedelse: Välj en platt standardiserad bana eller löpband under samma yttre förhållanden.",
        "2. Uppvärmning: 15–20 minuters mycket lätt uppvärmning, varav sista 10 min nära MAF-min.",
        "3. Testets genomförande: Spring i 40 minuter (eller 5 km) och håll pulsen konstant på MAF-target (±2 bpm).",
        "4. Loggning: Notera distans och km-tider. Jämför distansen vid samma MAF-puls över månader för att mäta aerobt framsteg!"
    ]

    return {
        "age": valid_age,
        "base_maf": round(base_maf),
        "adjustment": adj,
        "category_desc": cat_desc,
        "maf_target": round(target),
        "maf_min": round(min_maf),
        "maf_max": round(target),
        "range_str": f"{round(min_maf)} – {round(target)} bpm",
        "warmup_range_str": f"{round(warmup_low)} – {round(min_maf)} bpm",
        "maf_test_steps": maf_test_steps,
        "description": "Maximal aerob fettförbränning & basbyggande enligt Dr. Philip Maffetone 180-principen.",
    }


def calculate_hr_zones(
    *,
    age: float = 40.0,
    resting_hr: float = 60.0,
    max_hr_override: float = 0.0,
    max_hr_source: Optional[str] = None,
    sex: str = "male",
    maf_adjustment: int = 0,
    maf_category: Optional[str] = None,
    training_years: Optional[float] = None,
    has_injury_or_illness: bool = False,
    is_beginner: bool = False,
) -> Dict:
    """Calculate 5-zone HR breakdown using Karvonen formula (HRR) and MAF 180.

    Karvonen formula:
      Target HR = Resting HR + Percentage * (Max HR - Resting HR)
    """
    v_age = float(age) if (age and float(age) > 0) else 40.0
    v_rest = float(resting_hr) if (resting_hr and float(resting_hr) > 0) else 60.0

    if max_hr_override and float(max_hr_override) > 0:
        v_max = float(max_hr_override)
        max_source = max_hr_source or "user"
    else:
        # Standard estimate formula fallback: 220 - age
        v_max = max(100.0, 220.0 - v_age)
        max_source = "formula"


    # Heart Rate Reserve (HRR)
    hrr = max(10.0, v_max - v_rest)

    # Karvonen zone boundaries (% of HRR)
    zone_defs = [
        ("Zon 1", "Uppvärmning & Återhämtning", 0.50, 0.60, "#3B82F6", "Mycket lätt effort, aktiv återhämtning"),
        ("Zon 2", "Lågintensiv / Fettförbränning", 0.60, 0.70, "#10B981", "Aerob basbygge, maximal fettförbränning"),
        ("Zon 3", "Aerob Kondition", 0.70, 0.80, "#F59E0B", "Förbättrar kondition och syreupptag"),
        ("Zon 4", "Anaerob Tröskel", 0.80, 0.90, "#EF4444", "Mjölksyraträning, hög ansträngning"),
        ("Zon 5", "Maximal Ansträngning", 0.90, 1.00, "#8B5CF6", "Spurt och kortvarig maxansträngning"),
    ]

    zones = []
    for name, title, pct_low, pct_high, color, desc in zone_defs:
        bpm_low = round(v_rest + pct_low * hrr)
        bpm_high = round(v_rest + pct_high * hrr)
        zones.append({
            "name": name,
            "title": title,
            "pct_low": int(pct_low * 100),
            "pct_high": int(pct_high * 100),
            "pct_range_str": f"{int(pct_low * 100)}–{int(pct_high * 100)}%",
            "bpm_low": bpm_low,
            "bpm_high": bpm_high,
            "bpm_range_str": f"{bpm_low} – {bpm_high} bpm",
            "color": color,
            "desc": desc,
        })

    maf = calculate_maf_hr(
        age=v_age,
        adjustment=maf_adjustment,
        category=maf_category,
        training_years=training_years,
        has_injury_or_illness=has_injury_or_illness,
        is_beginner=is_beginner,
    )

    return {
        "age": v_age,
        "resting_hr": round(v_rest),
        "max_hr": round(v_max),
        "max_source": max_source,
        "hrr": round(hrr),
        "zones": zones,
        "maf": maf,
    }
