"""
Prompt Store for HealthChat.

Systemprompterna ligger som redigerbara Markdown-filer under `prompts/` i stället
för hårdkodade i Python. Syftet är att prompten ska kunna finjusteras utan
kodändring, utan omstart och utan risk för att någon råkar bryta en trippelciterad
sträng mitt i en deploy.

Designval:
- **Varmladdning.** Filens mtime kontrolleras vid varje anrop. Ändrar du filen slår
  den igenom vid nästa meddelande. Cachen gör att disken bara läses när något faktiskt
  ändrats.
- **HTML-kommentarer strippas.** `<!-- ... -->` tas bort innan texten skickas till
  modellen, så att filen kan innehålla redigeringsanteckningar som modellen inte ser.
- **Fallback framför krasch.** Saknas eller går filen inte att läsa loggas ett tydligt
  fel och en inbyggd minimiprompt används. Chatten ska aldrig dö för att en promptfil
  råkat försvinna vid en deploy.
"""

import os
import re
import logging
import threading
from pathlib import Path
from typing import Dict, Optional, Tuple

logger = logging.getLogger("prompt_store")

# Katalogen kan flyttas med HEALTHCHAT_PROMPTS_DIR (t.ex. för att lägga lokalt
# anpassade prompter utanför git i drift).
PROMPTS_DIR = Path(
    os.environ.get("HEALTHCHAT_PROMPTS_DIR")
    or Path(__file__).resolve().parent / "prompts"
)

# name -> (mtime_ns, storlek, renderad text)
_cache: Dict[str, Tuple[int, int, str]] = {}
_cache_lock = threading.Lock()

_HTML_COMMENT = re.compile(r"<!--.*?-->", re.DOTALL)


def prompt_path(name: str) -> Path:
    """Sökväg till promptfilen för `name` (utan .md)."""
    safe = os.path.basename(str(name)).removesuffix(".md")
    return PROMPTS_DIR / f"{safe}.md"


def _render(raw: str) -> str:
    """Ta bort redigeringskommentarer och normalisera blankrader."""
    text = _HTML_COMMENT.sub("", raw)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def get_prompt(name: str, fallback: str = "") -> str:
    """
    Läs prompten `name` från `prompts/<name>.md`.

    Returnerar den renderade texten. Saknas filen loggas ett fel och `fallback`
    returneras - anroparen får alltid en användbar sträng tillbaka.
    """
    path = prompt_path(name)
    try:
        stat = path.stat()
        key = (stat.st_mtime_ns, stat.st_size)
    except OSError as e:
        logger.error(
            f"Promptfilen {path} kunde inte läsas ({e}). "
            f"Använder inbyggd reservprompt - kontrollera att katalogen {PROMPTS_DIR} finns."
        )
        return fallback

    with _cache_lock:
        cached = _cache.get(name)
        if cached and (cached[0], cached[1]) == key:
            return cached[2]

    try:
        rendered = _render(path.read_text(encoding="utf-8"))
    except OSError as e:
        logger.error(f"Kunde inte läsa {path}: {e}. Använder inbyggd reservprompt.")
        return fallback

    if not rendered:
        logger.error(f"Promptfilen {path} är tom efter rendering. Använder reservprompt.")
        return fallback

    with _cache_lock:
        _cache[name] = (key[0], key[1], rendered)

    logger.info(f"Laddade prompt '{name}' från {path} ({len(rendered)} tecken).")
    return rendered


def list_prompts() -> list:
    """Namnen på alla aktiva prompter (arkivet räknas inte)."""
    if not PROMPTS_DIR.is_dir():
        return []
    return sorted(p.stem for p in PROMPTS_DIR.glob("*.md"))


def clear_cache(name: Optional[str] = None) -> None:
    """Töm promptcachen. Används av tester och vid manuell omladdning."""
    with _cache_lock:
        if name is None:
            _cache.clear()
        else:
            _cache.pop(name, None)
