"""Chat orchestration for the web application.

A port of ``HealthChatApp._process_message``: the same query classification, the
same Garmin context selection and the same conversation memory. In the desktop
build this ran on a worker thread that pushed results into Tk; here it runs
inside the request handler and returns the answer to the browser.
"""

import logging
import re
from datetime import datetime, timedelta
from typing import Any, Dict, Optional, Tuple

logger = logging.getLogger("web_chat")


def _date_range_context(garmin_handler, query_lower: str) -> Optional[str]:
    """Build activity context when the question asks for a period of time."""
    time_period_match = re.search(r"(?:last|past)\s+(\d+)\s+(day|week|month)s?", query_lower)
    simple_period_match = re.search(r"(?:last|past|this)\s+(month|week|year)", query_lower)

    end_date = datetime.now()
    start_date = None

    if time_period_match:
        number = int(time_period_match.group(1))
        unit = time_period_match.group(2)
        if unit == "day":
            start_date = end_date - timedelta(days=number)
        elif unit == "week":
            start_date = end_date - timedelta(weeks=number)
        elif unit == "month":
            start_date = end_date - timedelta(days=number * 30)
    elif simple_period_match:
        period = simple_period_match.group(1)
        prefix = simple_period_match.group(0).split()[0]
        if period == "month":
            start_date = end_date.replace(day=1) if prefix == "this" else end_date - timedelta(days=30)
        elif period == "week":
            start_date = (
                end_date - timedelta(days=end_date.weekday()) if prefix == "this" else end_date - timedelta(days=7)
            )
        elif period == "year":
            start_date = end_date.replace(month=1, day=1) if prefix == "this" else end_date - timedelta(days=365)

    if start_date is None:
        return None

    logger.info(
        "Detected date range query: %s to %s",
        start_date.strftime("%Y-%m-%d"),
        end_date.strftime("%Y-%m-%d"),
    )

    try:
        activities = garmin_handler.get_activities_by_date(
            start_date.strftime("%Y-%m-%d"), end_date.strftime("%Y-%m-%d")
        )
    except Exception as exc:
        logger.error("Error fetching activities by date: %s", exc)
        return None

    header = f"=== Activities from {start_date.strftime('%Y-%m-%d')} to {end_date.strftime('%Y-%m-%d')}"
    if not activities:
        return f"{header} ===\nNo workouts or activities recorded during this period."

    parts = [f"{header} ({len(activities)} activities) ==="]
    for i, activity in enumerate(activities, 1):
        distance = activity.get("distance", 0) / 1000 if activity.get("distance") else 0
        duration = activity.get("duration", 0) / 60 if activity.get("duration") else 0
        parts.append(f"{i}. {activity.get('activityName', 'Unknown')} "
                     f"({activity.get('activityType', {}).get('typeKey', 'Unknown')})")
        parts.append(f"   Date: {activity.get('startTimeLocal', 'N/A')}")
        parts.append(f"   Distance: {distance:.2f} km")
        parts.append(f"   Duration: {duration:.1f} minutes")
        parts.append(f"   Calories: {activity.get('calories', 'N/A')}")
        parts.append("")
    return "\n".join(parts)


# Keyword routing, in priority order — identical to the desktop build.
TOPIC_ROUTES: Tuple[Tuple[Tuple[str, ...], str, Optional[int]], ...] = (
    (("pt", "coach", "personlig tränare", "analysera", "utvärdera", "hälsa", "form", "helhet",
      "all data", "overview", "summary"), "comprehensive", 15),
    (("sömn", "sömnskikringar", "sova", "sleep", "rest", "bed"), "sleep", None),
    (("body battery", "energi", "återhämtning", "återhämtningskapacitet", "energy"), "comprehensive", 10),
    (("träning", "träningspass", "pass", "löpning", "cykling", "activity", "activities",
      "workout", "run", "walk", "bike", "exercise"), "comprehensive", 15),
    (("steg", "stegräknare", "sträcka", "kalorier", "step", "walk", "distance", "calorie"), "summary", None),
    (("stress", "stressed", "tension"), "stress", None),
    (("respiration", "andning", "breathing", "breath"), "respiration", None),
    (("hydration", "vatten", "vätska", "water", "drink", "fluid"), "hydration", None),
    (("nutrition", "mat", "kost", "food", "eat", "meal", "diet", "protein", "carbs", "fat",
      "macros", "calories consumed", "food log", "logged"), "nutrition", None),
    (("trappor", "våningar", "floor", "climb", "stairs", "elevation"), "floors", None),
    (("intense", "intensity", "vigorous", "moderate"), "intensity", None),
    (("spo2", "syre", "oxygen", "pulse ox"), "spo2", None),
    (("hrv", "pulsvariabilitet", "heart rate variability", "variability"), "hrv", None),
    (("vo2", "kondition", "fitness age", "training status", "training load"), "training", None),
)


def build_garmin_context(garmin_handler, message: str) -> str:
    """Pick the right slice of Garmin data for the question being asked."""
    query_lower = message.lower()

    range_context = _date_range_context(garmin_handler, query_lower)
    if range_context is not None:
        return range_context

    activity_limit = 5
    if any(
        phrase in query_lower
        for phrase in ["show me more", "more activities", "all activities", "all my activities",
                       "show all", "recent activities"]
    ):
        activity_limit = 30

    number_match = re.search(r"(?:last|past|recent)\s+(\d+)", query_lower)
    if number_match:
        activity_limit = min(int(number_match.group(1)), 50)

    for keywords, data_type, limit in TOPIC_ROUTES:
        if any(word in query_lower for word in keywords):
            if limit is None:
                return garmin_handler.format_data_for_context(data_type)
            return garmin_handler.format_data_for_context(data_type, activity_limit=limit)

    return garmin_handler.format_data_for_context("comprehensive", activity_limit=activity_limit)


def process_message(workspace, message: str) -> Dict[str, Any]:
    """Answer one chat message, updating the workspace's conversation state."""
    if not workspace.ensure_ai_client():
        raise RuntimeError("Kunde inte initiera AI-klienten. Kontrollera dina inställningar.")

    garmin_context = ""
    if workspace.garmin_handler and workspace.authenticated:
        try:
            garmin_context = build_garmin_context(workspace.garmin_handler, message)
        except Exception as exc:
            logger.error("Could not build Garmin context: %s", exc)
            garmin_context = ""

    context_summary = ""
    if workspace.conversation_context:
        context_summary = "\n\nPrevious conversation context:\n"
        for conv in workspace.conversation_context[-5:]:
            context_summary += f"{conv.get('sender', 'User')}: {conv.get('message', '')[:100]}...\n"

    response = workspace.ai_client.chat(message, garmin_context + context_summary)

    now = datetime.now().isoformat()
    workspace.conversation_context.append({"sender": "You", "message": message, "timestamp": now})
    workspace.conversation_context.append({"sender": "HealthChat", "message": response, "timestamp": now})
    if len(workspace.conversation_context) > workspace.max_context_messages:
        workspace.conversation_context = workspace.conversation_context[-workspace.max_context_messages:]

    return workspace.add_message("HealthChat", response, "assistant")
