"""
Återhämtningstrender för HealthChat.

COACH AI fick tidigare bara ett enstaka nattvärde i sitt sammanhang - "Senaste HRV:
46 ms". Det säger ingenting utan referens: modellen kan omöjligt veta om 46 ms är bra
*för den här personen*. Den här modulen räknar i stället ut ett snitt för de senaste
dagarna och ställer det mot en baslinje från perioden strax innan, så att coachen kan
resonera om riktning i stället för att gissa.

Fönstren följer samma upplägg som trösklarna i prompts/coach_system.md:
    senaste 7 dagarna  mot  de 14 dagarna närmast före.

Larmtrösklar (avsnitt 2 i prompten):
    vilopuls  +5 %  eller mer över baslinjen  -> belastning
    HRV      -10 %  eller mer under baslinjen -> belastning
    sömn     -10 %  eller mer under baslinjen -> otillräcklig återhämtning

Modulen är medvetet fri från databas- och UI-beroenden så att den kan enhetstestas
isolerat, precis som calorie_calc.py.

Två fallgropar som hanteras explicit:

1. **Nollor är inte mätvärden.** `upsert_daily_summary` skriver `resting_hr=0` när
   Garmin inte lämnat något värde. Räknas nollan med dras snittet ned och trenden blir
   påhittad. Alla icke-positiva värden filtreras därför bort.
2. **För få dagar är ingen trend.** Med två mätpunkter är "trenden" brus. Räcker inte
   underlaget rapporteras det uttryckligen i stället för att ett procenttal presenteras
   som om det betydde något.
"""

from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional, Sequence

RECENT_DAYS = 7
BASELINE_DAYS = 14

# Minsta antal faktiska mätvärden för att ett snitt ska redovisas som en trend.
MIN_RECENT = 3
MIN_BASELINE = 5


def _parse_day(value: Any) -> Optional[date]:
    """Tolka ett datumfält som `date`. Returnerar None för värden som inte går att läsa."""
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if not value:
        return None
    text = str(value).strip()[:10]
    try:
        return datetime.strptime(text, "%Y-%m-%d").date()
    except ValueError:
        return None


def _numeric(value: Any) -> Optional[float]:
    """Tolka ett mätvärde som float. Nollor och negativa tal räknas som saknad data."""
    if value is None:
        return None
    try:
        num = float(value)
    except (TypeError, ValueError):
        return None
    if num <= 0:
        return None
    return num


def _mean(values: Sequence[float]) -> Optional[float]:
    return sum(values) / len(values) if values else None


def compute_trend(
    rows: Optional[Sequence[Dict[str, Any]]],
    value_key: str,
    *,
    higher_is_better: bool,
    warn_pct: float,
    today: Optional[date] = None,
    date_key: str = "date",
    recent_days: int = RECENT_DAYS,
    baseline_days: int = BASELINE_DAYS,
    min_recent: int = MIN_RECENT,
    min_baseline: int = MIN_BASELINE,
) -> Dict[str, Any]:
    """
    Jämför snittet för de senaste `recent_days` dagarna mot de `baseline_days`
    dagarna närmast före.

    `higher_is_better` avgör vilken riktning som är oroande: vilopuls som stiger är
    sämre, HRV och sömn som sjunker är sämre. `warn_pct` är hur stor avvikelse i fel
    riktning som ska flaggas, angiven som positivt tal (5.0 = 5 %).

    Returnerar alltid en dict med `status`, som är en av:
        "no_data"        - inga mätvärden alls
        "insufficient"   - för få dagar för att uttala sig om en trend
        "ok"             - inom normalvariation
        "warn"           - avviker i ogynnsam riktning över tröskeln
        "improved"       - avviker tydligt i gynnsam riktning
    """
    ref_day = today or datetime.now().date()

    recent_start = ref_day - timedelta(days=recent_days - 1)
    baseline_end = recent_start - timedelta(days=1)
    baseline_start = baseline_end - timedelta(days=baseline_days - 1)

    recent: List[float] = []
    baseline: List[float] = []
    latest_value: Optional[float] = None
    latest_day: Optional[date] = None

    for row in rows or []:
        if not isinstance(row, dict):
            continue
        day = _parse_day(row.get(date_key) or row.get("start_time"))
        num = _numeric(row.get(value_key))
        if day is None or num is None:
            continue
        if recent_start <= day <= ref_day:
            recent.append(num)
            if latest_day is None or day > latest_day:
                latest_day, latest_value = day, num
        elif baseline_start <= day <= baseline_end:
            baseline.append(num)

    result: Dict[str, Any] = {
        "value_key": value_key,
        "latest": round(latest_value, 1) if latest_value is not None else None,
        "latest_date": latest_day.isoformat() if latest_day else None,
        "recent_avg": None,
        "baseline_avg": None,
        "pct_change": None,
        "n_recent": len(recent),
        "n_baseline": len(baseline),
        "status": "no_data",
    }

    if not recent and not baseline:
        return result

    recent_avg = _mean(recent)
    baseline_avg = _mean(baseline)
    result["recent_avg"] = round(recent_avg, 1) if recent_avg is not None else None
    result["baseline_avg"] = round(baseline_avg, 1) if baseline_avg is not None else None

    if len(recent) < min_recent or len(baseline) < min_baseline or not baseline_avg:
        result["status"] = "insufficient"
        return result

    pct = (recent_avg - baseline_avg) / baseline_avg * 100.0
    result["pct_change"] = round(pct, 1)

    adverse = -pct if higher_is_better else pct
    if adverse >= warn_pct:
        result["status"] = "warn"
    elif -adverse >= warn_pct:
        result["status"] = "improved"
    else:
        result["status"] = "ok"
    return result


# Mätvärden som sammanfattas, i den ordning de presenteras för modellen.
# (etikett, enhet, value_key, higher_is_better, warn_pct, oroande, gynnsamt)
_METRICS = (
    ("Vilopuls", "bpm", "resting_hr", False, 5.0, "förhöjd - tecken på belastning", "sänkt - god anpassning"),
    ("HRV", "ms", "last_night_avg", True, 10.0, "sänkt - ökad belastning eller stress", "höjd - god återhämtning"),
    ("Sömn", "h", "total_sleep_hours", True, 10.0, "kortare än vanligt", "längre än vanligt"),
)


def _format_number(value: float, unit: str) -> str:
    """Ett mätvärde med svensk decimalkomma och enhet: 7.25 -> "7,3 h"."""
    text = f"{value:.1f}".rstrip("0").rstrip(".").replace(".", ",")
    return f"{text} {unit}".strip()


def format_trend_line(
    label: str,
    unit: str,
    trend: Dict[str, Any],
    adverse_text: str,
    favourable_text: str,
) -> Optional[str]:
    """Formatera en trend som en rad för AI-sammanhanget. None om data saknas helt."""
    status = trend["status"]
    if status == "no_data":
        return None

    if trend["latest"] is not None:
        head = f"{label}: {_format_number(trend['latest'], unit)} senast uppmätt."
    else:
        head = f"{label}:"

    if status == "insufficient":
        return (
            f"{head} Otillräckligt underlag för trend "
            f"({trend['n_recent']} av {MIN_RECENT} dagar senaste veckan, "
            f"{trend['n_baseline']} av {MIN_BASELINE} i baslinjen) "
            f"- dra inga slutsatser om riktning."
        )

    pct = trend["pct_change"]
    sign = "+" if pct > 0 else ""
    pct_text = f"{sign}{pct:.1f}".replace(".", ",")
    verdict = {
        "warn": f"⚠️ {adverse_text}",
        "improved": f"✅ {favourable_text}",
    }.get(status, "inom normalvariation")

    return (
        f"{head} Snitt {RECENT_DAYS}d {_format_number(trend['recent_avg'], unit)} "
        f"mot baslinje ({BASELINE_DAYS}d före) {_format_number(trend['baseline_avg'], unit)} "
        f"= {pct_text} % - {verdict}."
    )


def build_trend_lines(
    daily_summary: Optional[Sequence[Dict[str, Any]]] = None,
    hrv: Optional[Sequence[Dict[str, Any]]] = None,
    sleep: Optional[Sequence[Dict[str, Any]]] = None,
    today: Optional[date] = None,
) -> List[str]:
    """
    Bygg de rader om återhämtningstrender som skickas till COACH AI.

    Tar historik rakt från `GarminDatabase.get_*_history()`. Returnerar en tom lista
    när ingen av källorna har användbara mätvärden - anroparen avgör då själv vad som
    ska sägas om avsaknaden.
    """
    sources = {
        "resting_hr": daily_summary,
        "last_night_avg": hrv,
        "total_sleep_hours": sleep,
    }

    lines: List[str] = []
    for label, unit, key, higher_better, warn_pct, adverse, favourable in _METRICS:
        trend = compute_trend(
            sources.get(key),
            key,
            higher_is_better=higher_better,
            warn_pct=warn_pct,
            today=today,
        )
        line = format_trend_line(label, unit, trend, adverse, favourable)
        if line:
            lines.append(line)
    return lines


def history_days_needed() -> int:
    """Hur många dagars historik som måste hämtas för att fylla båda fönstren."""
    return RECENT_DAYS + BASELINE_DAYS
