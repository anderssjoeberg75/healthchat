"""
Profile Sync Module for HealthChat.
Aggregates personal profile metrics (sex, height_cm, age, weight_kg, resting_hr, max_hr)
from connected external services (Garmin, Fitbit, Strava, Withings) and local DB history.
"""

import logging
from datetime import datetime
from typing import Dict, Any, Optional, List

logger = logging.getLogger("profile_sync")


def fetch_external_profile_metrics(
    db=None,
    garmin_handler=None,
    fitbit_handler=None,
    strava_handler=None,
    withings_handler=None
) -> Dict[str, Any]:
    """
    Query active connected service handlers and local DB history to extract the latest available
    profile metrics (sex, height_cm, age, weight_kg, resting_hr, max_hr).

    Returns a dict:
    {
        "metrics": {
            "sex": "male"|"female",
            "height_cm": float,
            "age": float,
            "weight_kg": float,
            "resting_hr": float,
            "max_hr": float
        },
        "sources": ["Garmin", "Withings", "Databas"]
    }
    """
    merged_metrics: Dict[str, Any] = {}
    contributing_sources: List[str] = []

    # 1. DB Fallback (Latest body_composition and daily_summary)
    if db:
        try:
            db_sources = []
            latest_comp = db.get_latest_body_composition()
            if latest_comp and isinstance(latest_comp, dict):
                w = float(latest_comp.get("weight_kg") or 0.0)
                if w > 0:
                    merged_metrics["weight_kg"] = round(w, 1)
                    db_sources.append("Vikt (Databas)")
                if latest_comp.get("fat_ratio_pct") and float(latest_comp["fat_ratio_pct"]) > 0:
                    merged_metrics["fat_ratio_pct"] = round(float(latest_comp["fat_ratio_pct"]), 1)
                if latest_comp.get("muscle_mass_kg") and float(latest_comp["muscle_mass_kg"]) > 0:
                    merged_metrics["muscle_mass_kg"] = round(float(latest_comp["muscle_mass_kg"]), 1)
                if latest_comp.get("bone_mass_kg") and float(latest_comp["bone_mass_kg"]) > 0:
                    merged_metrics["bone_mass_kg"] = round(float(latest_comp["bone_mass_kg"]), 1)
                if latest_comp.get("water_pct") and float(latest_comp["water_pct"]) > 0:
                    merged_metrics["water_pct"] = round(float(latest_comp["water_pct"]), 1)
                if latest_comp.get("bmi") and float(latest_comp["bmi"]) > 0:
                    merged_metrics["bmi"] = round(float(latest_comp["bmi"]), 1)


            daily_hist = db.get_daily_summary_history(days=30)
            if daily_hist:
                for day in reversed(daily_hist):
                    r_hr = float(day.get("resting_hr") or day.get("restingHeartRate") or 0.0)
                    if r_hr > 0:
                        merged_metrics["resting_hr"] = round(r_hr, 1)
                        db_sources.append("Vilopuls (Databas)")
                        break
            if db_sources:
                contributing_sources.append("Databas")
        except Exception as e:
            logger.warning(f"Error extracting DB profile metrics: {e}")

    # 2. Garmin Handler
    if garmin_handler:
        try:
            g_data = {}
            if hasattr(garmin_handler, "fetch_user_profile_data"):
                g_data = garmin_handler.fetch_user_profile_data()
            elif hasattr(garmin_handler, "client") and garmin_handler.client:
                prof = None
                try:
                    prof = garmin_handler.client.get_userprofile_settings()
                except Exception:
                    pass
                if not prof:
                    try:
                        prof = garmin_handler.client.get_user_profile()
                    except Exception:
                        pass
                if isinstance(prof, dict):
                    udata = prof.get("userData", {})
                    if isinstance(udata, dict):
                        if udata.get("gender"):
                            gen = str(udata.get("gender")).lower()
                            g_data["sex"] = "female" if "female" in gen or gen == "f" else "male"
                        if udata.get("height"):
                            g_data["height_cm"] = float(udata.get("height"))
                        if udata.get("weight"):
                            raw_w = float(udata.get("weight"))
                            g_data["weight_kg"] = round(raw_w / 1000.0 if raw_w > 300 else raw_w, 1)
                        if udata.get("maxHeartRate") or udata.get("defaultMaxHeartRate"):
                            g_data["max_hr"] = float(udata.get("maxHeartRate") or udata.get("defaultMaxHeartRate"))
                        if udata.get("restingHeartRate"):
                            g_data["resting_hr"] = float(udata.get("restingHeartRate"))
                        if udata.get("birthDate"):
                            try:
                                bdate = str(udata.get("birthDate"))
                                byear = int(bdate.split("-")[0])
                                g_data["age"] = float(datetime.now().year - byear)
                            except Exception:
                                pass

            if g_data:
                for k, v in g_data.items():
                    if v is not None and v != 0 and v != "":
                        merged_metrics[k] = v
                contributing_sources.append("Garmin")
        except Exception as e:
            logger.warning(f"Error fetching Garmin profile metrics: {e}")

    # 3. Fitbit Handler
    if fitbit_handler and hasattr(fitbit_handler, "is_authenticated") and fitbit_handler.is_authenticated():
        try:
            f_data = {}
            if hasattr(fitbit_handler, "fetch_user_profile"):
                f_data = fitbit_handler.fetch_user_profile()
            if f_data:
                for k, v in f_data.items():
                    if v is not None and v != 0 and v != "":
                        merged_metrics[k] = v
                contributing_sources.append("Fitbit")
        except Exception as e:
            logger.warning(f"Error fetching Fitbit profile metrics: {e}")

    # 4. Strava Handler
    if strava_handler and hasattr(strava_handler, "is_authenticated") and strava_handler.is_authenticated():
        try:
            s_data = {}
            if hasattr(strava_handler, "fetch_athlete_profile"):
                s_data = strava_handler.fetch_athlete_profile()
            if s_data:
                for k, v in s_data.items():
                    if v is not None and v != 0 and v != "":
                        merged_metrics[k] = v
                contributing_sources.append("Strava")
        except Exception as e:
            logger.warning(f"Error fetching Strava profile metrics: {e}")

    # 5. Withings Handler
    if withings_handler:
        try:
            w_data = {}
            if hasattr(withings_handler, "fetch_profile_data"):
                w_data = withings_handler.fetch_profile_data()
            if w_data:
                for k, v in w_data.items():
                    if v is not None and v != 0 and v != "":
                        merged_metrics[k] = v
                contributing_sources.append("Withings")
        except Exception as e:
            logger.warning(f"Error fetching Withings profile metrics: {e}")

    # Calculate default Max HR if age exists and max_hr is missing
    if "age" in merged_metrics and ("max_hr" not in merged_metrics or merged_metrics["max_hr"] == 0):
        try:
            merged_metrics["max_hr"] = float(round(220 - float(merged_metrics["age"])))
        except Exception:
            pass

    # Calculate BMI if height_cm and weight_kg exist and bmi is missing/zero
    if ("bmi" not in merged_metrics or merged_metrics["bmi"] == 0) and merged_metrics.get("height_cm") and merged_metrics.get("weight_kg"):
        try:
            h_m = float(merged_metrics["height_cm"]) / 100.0
            w_k = float(merged_metrics["weight_kg"])
            if h_m > 0 and w_k > 0:
                merged_metrics["bmi"] = round(w_k / (h_m ** 2), 1)
        except Exception:
            pass

    # Unique list of sources
    unique_sources = []
    for src in contributing_sources:
        if src not in unique_sources:
            unique_sources.append(src)

    return {
        "metrics": merged_metrics,
        "sources": unique_sources
    }
