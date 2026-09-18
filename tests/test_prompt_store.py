"""Tester för prompt_store och COACH AI:s systemprompt.

Två syften:
1. Verifiera laddningsmekaniken (varmladdning, kommentarsstrippning, fallback).
2. Låsa fast de säkerhetsregler som inte får försvinna ur prompten - framför allt
   det absoluta förbudet mot medicinska diagnoser. Det testet ska failla högljutt
   om någon råkar redigera bort regeln.
"""

import logging

import pytest

import prompt_store
from ai_client import AIClient


@pytest.fixture(autouse=True)
def _clear_cache():
    prompt_store.clear_cache()
    yield
    prompt_store.clear_cache()


# --- Laddningsmekanik -------------------------------------------------------

def test_coach_system_prompt_loads_from_file():
    """Prompten hämtas från prompts/coach_system.md, inte från reservprompten."""
    prompt = AIClient.get_default_system_prompt()
    assert prompt.strip()
    assert prompt != AIClient.FALLBACK_COACH_PROMPT
    assert "COACH AI" in prompt


def test_html_comments_are_stripped(tmp_path, monkeypatch):
    """Redigeringsanteckningar i filen ska aldrig nå modellen."""
    monkeypatch.setattr(prompt_store, "PROMPTS_DIR", tmp_path)
    (tmp_path / "demo.md").write_text(
        "<!-- intern anteckning -->\nSynlig text.\n<!--\nflerradig\n-->\nMer text.",
        encoding="utf-8",
    )
    rendered = prompt_store.get_prompt("demo")
    assert "intern anteckning" not in rendered
    assert "flerradig" not in rendered
    assert "Synlig text." in rendered
    assert "Mer text." in rendered


def test_edits_take_effect_without_restart(tmp_path, monkeypatch):
    """Ändrad fil ska slå igenom vid nästa anrop (varmladdning via mtime)."""
    monkeypatch.setattr(prompt_store, "PROMPTS_DIR", tmp_path)
    path = tmp_path / "demo.md"

    path.write_text("Version ett.", encoding="utf-8")
    assert prompt_store.get_prompt("demo") == "Version ett."

    # Skriv ny text med annan längd så att (mtime_ns, storlek) garanterat skiljer sig
    # även på filsystem med grov tidsupplösning.
    path.write_text("Version tva - annan langd.", encoding="utf-8")
    assert prompt_store.get_prompt("demo") == "Version tva - annan langd."


def test_missing_file_uses_fallback_and_logs_error(tmp_path, monkeypatch, caplog):
    """En saknad promptfil får aldrig stoppa ett svar - men ska synas i loggen."""
    monkeypatch.setattr(prompt_store, "PROMPTS_DIR", tmp_path)
    with caplog.at_level(logging.ERROR, logger="prompt_store"):
        result = prompt_store.get_prompt("finns_inte", fallback="RESERV")
    assert result == "RESERV"
    assert any("finns_inte" in r.message for r in caplog.records)


def test_empty_file_uses_fallback(tmp_path, monkeypatch):
    """En fil som bara innehåller kommentarer räknas som tom."""
    monkeypatch.setattr(prompt_store, "PROMPTS_DIR", tmp_path)
    (tmp_path / "tom.md").write_text("<!-- bara en kommentar -->\n", encoding="utf-8")
    assert prompt_store.get_prompt("tom", fallback="RESERV") == "RESERV"


def test_prompt_name_cannot_escape_directory(tmp_path, monkeypatch):
    """Ett promptnamn får inte kunna peka utanför promptkatalogen."""
    monkeypatch.setattr(prompt_store, "PROMPTS_DIR", tmp_path)
    assert prompt_store.prompt_path("../../etc/passwd").parent == tmp_path


def test_coach_system_is_listed():
    assert "coach_system" in prompt_store.list_prompts()


# --- Säkerhetsregler som inte får försvinna ---------------------------------

# Varje post: (beskrivning, lista av fraser där minst en måste finnas)
REQUIRED_SAFETY_RULES = [
    ("förbud mot att ställa diagnos", ["aldrig ställa", "ALDRIG ställa"]),
    ("förbud mot att utesluta diagnos", ["utesluta en medicinsk diagnos"]),
    ("förbud mot att friskförklara", ["friskförklara", "inget farligt"]),
    ("förbud mot läkemedelsrådgivning", ["läkemedel"]),
    ("hänvisning till vården", ["1177", "vårdcentral", "vårdgivare"]),
    ("inte medicinteknisk produkt", ["medicinteknisk produkt"]),
    ("röda flaggor", ["bröstsmärta"]),
]


@pytest.mark.parametrize("label,phrases", REQUIRED_SAFETY_RULES, ids=[r[0] for r in REQUIRED_SAFETY_RULES])
def test_active_prompt_contains_safety_rule(label, phrases):
    """prompts/coach_system.md måste innehålla varje säkerhetsregel.

    Failar detta test har någon redigerat bort en regel ur promptfilen. Regeln är
    det som håller HealthChat på rätt sida om gränsen mot medicinteknisk produkt -
    återställ den i stället för att ändra testet, om det inte är ett medvetet beslut.
    """
    prompt = AIClient.get_default_system_prompt()
    assert any(p in prompt for p in phrases), (
        f"Säkerhetsregeln '{label}' saknas i prompts/coach_system.md. "
        f"Förväntade minst en av: {phrases}"
    )


@pytest.mark.parametrize("label,phrases", REQUIRED_SAFETY_RULES[:6], ids=[r[0] for r in REQUIRED_SAFETY_RULES[:6]])
def test_fallback_prompt_contains_safety_rule(label, phrases):
    """Reservprompten i koden måste bära samma regler.

    Annars skulle en saknad promptfil tyst ta bort säkerhetsreglerna i stället för
    att bara degradera promptens kvalitet.
    """
    assert any(p in AIClient.FALLBACK_COACH_PROMPT for p in phrases), (
        f"Säkerhetsregeln '{label}' saknas i AIClient.FALLBACK_COACH_PROMPT."
    )


def test_diagnosis_ban_is_stated_as_absolute():
    """Förbudet ska vara formulerat som undantagslöst, inte som en rekommendation."""
    prompt = AIClient.get_default_system_prompt()
    assert "ABSOLUT REGEL" in prompt
    assert "undantagslös" in prompt


def test_archived_original_prompt_is_kept():
    """Originalprompten ska finnas kvar i arkivet och inte laddas av appen."""
    archived = prompt_store.PROMPTS_DIR / "archive" / "coach_system_v1_2026-09-17.md"
    assert archived.is_file(), "Den arkiverade originalprompten saknas."
    assert "coach_system_v1_2026-09-17" not in prompt_store.list_prompts()
