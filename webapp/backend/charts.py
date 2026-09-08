"""Server-side chart rendering.

The desktop app drew its dashboard with Matplotlib inside Tk canvases. The web
build renders the *same* figures headlessly (Agg) and serves them as PNG, so the
charts look pixel-for-pixel like the desktop ones — same sizes, colours, titles
and axis formatting — without reimplementing them in a JavaScript charting
library.
"""

import io
import json
import logging
from typing import Any, Dict, List, Optional, Tuple

import matplotlib

matplotlib.use("Agg")  # No display on a server.

import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.figure import Figure  # noqa: E402

logger = logging.getLogger(__name__)

plt.style.use("default")


def _format_axis_dates(ax, dates: List[str]) -> None:
    """Cleanly format X-axis date labels without overlapping text."""
    if not dates:
        return
    n = len(dates)
    if n > 10:
        step = max(1, n // 8)
        indices = list(range(0, n, step))
        if indices[-1] != n - 1:
            indices.append(n - 1)
        ax.set_xticks(indices)
        ax.set_xticklabels([dates[i] for i in indices], rotation=35, ha="right", fontsize=8)
    else:
        ax.set_xticks(range(n))
        ax.set_xticklabels(dates, rotation=35, ha="right", fontsize=8)


def prepare_chart_series(
    data_list: Optional[List[Dict[str, Any]]], value_key: str, default_val: float = 0.0
) -> Tuple[List[str], List[float]]:
    """Sort records by date and return (labels, values) ready for plotting."""
    if not data_list:
        return [], []
    valid_items = [d for d in data_list if (d.get("date") or d.get("start_time"))]
    sorted_list = sorted(valid_items, key=lambda x: str(x.get("date") or x.get("start_time") or ""))

    if not sorted_list:
        return [], []

    years = set(
        str(x.get("date") or x.get("start_time") or "")[:4]
        for x in sorted_list
        if len(str(x.get("date") or "")) >= 4
    )
    use_year = len(years) > 1

    dates: List[str] = []
    vals: List[float] = []
    for d in sorted_list:
        dt_raw = str(d.get("date") or d.get("start_time") or "")[:10]
        if len(dt_raw) < 10:
            continue
        dates.append(dt_raw[2:] if use_year else dt_raw[5:])
        vals.append(float(d.get(value_key) or default_val))

    return dates, vals


def _style_axis(ax) -> None:
    ax.set_facecolor("#FFFFFF")
    ax.tick_params(colors="#374151", labelsize=8)
    ax.grid(True, linestyle="--", alpha=0.4, color="#E5E7EB")
    for spine in ax.spines.values():
        spine.set_color("#E5E7EB")


def _to_png(figure: Figure) -> bytes:
    buffer = io.BytesIO()
    figure.savefig(buffer, format="png", facecolor=figure.get_facecolor())
    plt.close(figure)
    return buffer.getvalue()


# --- Dashboard tab ---------------------------------------------------------


def render_weekly_activity(act_hist: List[Dict[str, Any]]) -> bytes:
    """Bar chart: training distance per day (Dashboard, 'Weekly Activity Summary')."""
    figure = Figure(figsize=(7, 3.2), dpi=95, facecolor="#FFFFFF")
    figure.subplots_adjust(left=0.1, right=0.95, top=0.88, bottom=0.25)
    ax = figure.add_subplot(1, 1, 1, facecolor="#FFFFFF")
    _style_axis(ax)

    dates, dist = prepare_chart_series(act_hist, "distance_km")
    if dates:
        ax.bar(dates, dist, color="#0078D4", alpha=0.85, width=0.45)
        ax.set_title("Träningsdistans per dag (km)", fontsize=9, fontweight="bold", color="#1F2937", pad=4)
        _format_axis_dates(ax, dates)
    else:
        ax.text(0.5, 0.5, "Inga aktiviteter registrerade", ha="center", va="center", color="#9CA3AF")
    return _to_png(figure)


def render_bb_sleep_stress(
    sleep_hist: List[Dict[str, Any]],
    bb_hist: List[Dict[str, Any]],
    stress_hist: List[Dict[str, Any]],
) -> bytes:
    """Three-panel figure: Body Battery, sleep and stress trends."""
    figure = Figure(figsize=(11, 4.5), dpi=95, facecolor="#FFFFFF")
    figure.subplots_adjust(hspace=0.55, wspace=0.3, left=0.07, right=0.96, top=0.9, bottom=0.22)

    ax_bb = figure.add_subplot(1, 3, 1, facecolor="#FFFFFF")
    ax_sleep = figure.add_subplot(1, 3, 2, facecolor="#FFFFFF")
    ax_stress = figure.add_subplot(1, 3, 3, facecolor="#FFFFFF")
    for ax in (ax_bb, ax_sleep, ax_stress):
        _style_axis(ax)

    dates, charged = prepare_chart_series(bb_hist, "charged")
    if dates:
        ax_bb.plot(dates, charged, color="#10B981", marker="o", linewidth=2.0, markersize=3)
        ax_bb.set_title("Body Battery Uppladdat (+)", fontsize=9, fontweight="bold", color="#1F2937", pad=4)
        _format_axis_dates(ax_bb, dates)
    else:
        ax_bb.text(0.5, 0.5, "Ingen Body Battery data", ha="center", va="center", color="#9CA3AF")

    dates, tot = prepare_chart_series(sleep_hist, "total_sleep_hours")
    if dates:
        ax_sleep.bar(dates, tot, color="#8B5CF6", alpha=0.75, width=0.45)
        ax_sleep.set_title("Totalt sömn (timmar)", fontsize=9, fontweight="bold", color="#1F2937", pad=4)
        _format_axis_dates(ax_sleep, dates)
    else:
        ax_sleep.text(0.5, 0.5, "Ingen sömndata", ha="center", va="center", color="#9CA3AF")

    dates, avg_s = prepare_chart_series(stress_hist, "average")
    if dates:
        ax_stress.plot(dates, avg_s, color="#FF5722", marker="s", linewidth=1.8, markersize=3)
        ax_stress.set_title("Genomsnittlig Stress", fontsize=9, fontweight="bold", color="#1F2937", pad=4)
        _format_axis_dates(ax_stress, dates)
    else:
        ax_stress.text(0.5, 0.5, "Ingen stressdata", ha="center", va="center", color="#9CA3AF")

    return _to_png(figure)


# --- EvoLab tab ------------------------------------------------------------


def render_evolab(
    db,
    days_range: int,
    sleep_hist: List[Dict[str, Any]],
    bb_hist: List[Dict[str, Any]],
    stress_hist: List[Dict[str, Any]],
    hrv_hist: List[Dict[str, Any]],
    act_hist: List[Dict[str, Any]],
    body_comp: Optional[Dict[str, Any]],
    daily_summary_hist: Optional[List[Dict[str, Any]]] = None,
) -> bytes:
    """The seven-panel EvoLab analytics figure."""
    figure = Figure(figsize=(11, 13), dpi=95, facecolor="#FFFFFF")
    figure.subplots_adjust(hspace=0.5, wspace=0.28, left=0.08, right=0.95, top=0.96, bottom=0.07)

    ax_load = figure.add_subplot(4, 2, 1, facecolor="#FFFFFF")
    ax_rhr = figure.add_subplot(4, 2, 2, facecolor="#FFFFFF")
    ax_hrv = figure.add_subplot(4, 2, 3, facecolor="#FFFFFF")
    ax_weight = figure.add_subplot(4, 2, 4, facecolor="#FFFFFF")
    ax_zones = figure.add_subplot(4, 2, 5, facecolor="#FFFFFF")
    ax_dist = figure.add_subplot(4, 2, 6, facecolor="#FFFFFF")
    ax_calories = figure.add_subplot(4, 2, 7, facecolor="#FFFFFF")

    for ax in (ax_load, ax_rhr, ax_hrv, ax_weight, ax_zones, ax_dist, ax_calories):
        _style_axis(ax)

    # 1. Training load / distance trend
    dates, dist = prepare_chart_series(act_hist, "distance_km")
    if dates:
        ax_load.plot(dates, dist, color="#0078D4", marker="o", linewidth=2.0)
        ax_load.set_title("Träningsbelastning & Distans Trend (km)", fontsize=9, fontweight="bold", color="#1F2937")
        _format_axis_dates(ax_load, dates)
    else:
        ax_load.text(0.5, 0.5, "Inga träningspass registrerade", ha="center", va="center", color="#9CA3AF")
        ax_load.set_title("Träningsbelastning & Distans Trend", fontsize=9, fontweight="bold", color="#1F2937")

    # 2. Resting heart rate
    rhr_map: Dict[str, float] = {}
    for d in daily_summary_hist or []:
        dt = d.get("date")
        rhr = d.get("resting_hr", 0)
        if dt and rhr and rhr > 0:
            rhr_map[dt] = rhr

    for s in sleep_hist or []:
        dt = s.get("date")
        if not dt:
            continue
        rhr = s.get("resting_hr") or s.get("resting_heart_rate", 0)
        if not rhr and s.get("raw_json"):
            try:
                raw = json.loads(s["raw_json"]) if isinstance(s["raw_json"], str) else s["raw_json"]
                rhr = raw.get("restingHeartRate") or raw.get("resting_hr", 0)
            except Exception:
                pass
        if rhr and rhr > 0:
            rhr_map[dt] = rhr

    if rhr_map:
        sorted_dates = sorted(rhr_map.keys())
        years = set(dt[:4] for dt in sorted_dates if len(dt) >= 4)
        use_yr = len(years) > 1
        rhr_dates = [dt[2:] if use_yr else dt[5:] for dt in sorted_dates]
        rhr_vals = [rhr_map[dt] for dt in sorted_dates]
        ax_rhr.plot(rhr_dates, rhr_vals, color="#EC4899", marker="o", linewidth=2.0, markersize=3)
        ax_rhr.set_title("Vilo-Hjärtfrekvens / Vilopuls (bpm)", fontsize=9, fontweight="bold", color="#1F2937")
        _format_axis_dates(ax_rhr, rhr_dates)
    else:
        ax_rhr.text(0.5, 0.5, "Vilopuls: Kör Check-in för att läsa sömndata", ha="center", va="center", color="#9CA3AF")
        ax_rhr.set_title("Vilo-Hjärtfrekvens / Vilopuls Trend", fontsize=9, fontweight="bold", color="#1F2937")

    # 3. HRV
    dates, hrv_val = prepare_chart_series(hrv_hist, "last_night_avg")
    if dates:
        ax_hrv.plot(dates, hrv_val, color="#10B981", marker="^", linewidth=2.0)
        ax_hrv.set_title("Nattlig HRV Trend (ms)", fontsize=9, fontweight="bold", color="#1F2937")
        _format_axis_dates(ax_hrv, dates)
    else:
        ax_hrv.text(0.5, 0.5, "HRV: Synka Garmin för pulsvariabilitet", ha="center", va="center", color="#9CA3AF")
        ax_hrv.set_title("Nattlig HRV Trend", fontsize=9, fontweight="bold", color="#1F2937")

    # 4. Weight & body composition
    body_hist = db.get_body_composition_history(days=days_range) if db else []
    if body_hist:
        dates, w_vals = prepare_chart_series(body_hist, "weight_kg")
        valid_pairs = [(d, w) for d, w in zip(dates, w_vals) if w > 0]
        if valid_pairs:
            vd, vw = zip(*valid_pairs)
            ax_weight.plot(vd, vw, color="#3B82F6", marker="s", linewidth=2.0, markersize=4)
            ax_weight.set_title("Withings & Fitbit Vikt-trend (kg)", fontsize=9, fontweight="bold", color="#1F2937")
            _format_axis_dates(ax_weight, list(vd))
        else:
            ax_weight.text(0.5, 0.5, "Vikt-trend: Synka Withings/Fitbit", ha="center", va="center", color="#9CA3AF")
            ax_weight.set_title("Withings Vikt & Kroppssammansättning", fontsize=9, fontweight="bold", color="#1F2937")
    elif body_comp and body_comp.get("weight_kg"):
        ax_weight.text(
            0.5,
            0.5,
            f"Vikt: {body_comp.get('weight_kg')} kg | Fett: {body_comp.get('fat_ratio_pct', 'N/A')}%",
            ha="center",
            va="center",
            color="#1F2937",
            fontsize=11,
            fontweight="bold",
        )
        ax_weight.set_title("Withings Vikt & Kroppssammansättning", fontsize=9, fontweight="bold", color="#1F2937")
    else:
        ax_weight.text(0.5, 0.5, "Vikt: Anslut Withings eller Fitbit", ha="center", va="center", color="#9CA3AF")
        ax_weight.set_title("Vikt & Kroppssammansättning", fontsize=9, fontweight="bold", color="#1F2937")

    # 5. Heart rate zone distribution
    ax_zones.pie(
        [15, 35, 30, 15, 5],
        labels=["Z1", "Z2", "Z3", "Z4", "Z5"],
        colors=["#93C5FD", "#60A5FA", "#3B82F6", "#2563EB", "#1D4ED8"],
        autopct="%1.0f%%",
        startangle=90,
    )
    ax_zones.set_title("Pulszondistribution Träning", fontsize=9, fontweight="bold", color="#1F2937")

    # 6. Volume / energy per session
    dates, cals = prepare_chart_series(act_hist, "calories")
    if dates and any(c > 0 for c in cals):
        ax_dist.bar(dates, cals, color="#F59E0B", alpha=0.85, width=0.45)
        ax_dist.set_title("Kaloriförbrukning per Pass (kcal)", fontsize=9, fontweight="bold", color="#1F2937")
        _format_axis_dates(ax_dist, dates)
    elif dates:
        dates, durations = prepare_chart_series(act_hist, "duration_min")
        ax_dist.bar(dates, durations, color="#10B981", alpha=0.85, width=0.45)
        ax_dist.set_title("Träningstid per Pass (min)", fontsize=9, fontweight="bold", color="#1F2937")
        _format_axis_dates(ax_dist, dates)
    else:
        ax_dist.text(0.5, 0.5, "Träningsvolym: Inga aktiviteter sparade", ha="center", va="center", color="#9CA3AF")
        ax_dist.set_title("Träningsvolym & Kalorier", fontsize=9, fontweight="bold", color="#1F2937")

    # 7. Daily calorie burn (stacked)
    cb_hist = db.get_calorie_burn_history(days_range) if db else []
    cb_dates, resting_vals = prepare_chart_series(cb_hist, "resting_burn")
    _, steps_vals = prepare_chart_series(cb_hist, "steps_burn")
    _, workout_vals = prepare_chart_series(cb_hist, "workout_burn")
    has_burn = cb_dates and any((r + s + w) > 0 for r, s, w in zip(resting_vals, steps_vals, workout_vals))
    if has_burn:
        base_steps = list(resting_vals)
        base_workout = [r + s for r, s in zip(resting_vals, steps_vals)]
        ax_calories.bar(cb_dates, resting_vals, color="#F59E0B", width=0.5, label="Vila (BMR)")
        ax_calories.bar(cb_dates, steps_vals, bottom=base_steps, color="#0078D4", width=0.5, label="Steg")
        ax_calories.bar(cb_dates, workout_vals, bottom=base_workout, color="#EF4444", width=0.5, label="Träning")
        ax_calories.set_title("Kaloriförbränning per dag (kcal)", fontsize=9, fontweight="bold", color="#1F2937")
        ax_calories.legend(fontsize=7, loc="upper left", framealpha=0.6)
        _format_axis_dates(ax_calories, cb_dates)
    else:
        ax_calories.text(
            0.5,
            0.5,
            "Kaloriförbränning: byggs upp allt\neftersom du använder appen",
            ha="center",
            va="center",
            color="#9CA3AF",
        )
        ax_calories.set_title("Kaloriförbränning per dag", fontsize=9, fontweight="bold", color="#1F2937")

    return _to_png(figure)
