"""Regressionsskydd mot hårdkodade lösenord och API-nycklar i repot.

Testet läser källfilerna och letar efter tilldelningar där ett hemlighetsliknande
namn får ett literalt värde. Avsikten är att fånga när ett lösenord smyger
tillbaka in i en konfigurationsmall, en systemd-enhet eller ett kodavsnitt -
inte att vara en fullständig hemlighetsskanner.
"""

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent

SCANNED_SUFFIXES = {".py", ".service", ".sql", ".sh", ".js", ".json", ".yml", ".yaml"}
SCANNED_EXTRA_NAMES = {".env.example"}
SKIPPED_DIRS = {".git", "__pycache__", "temp", "scratch", "build", "dist", "venv", ".venv"}

SECRET_KEY = r"[A-Za-z_]*(?:password|passwd|secret|api[_-]?key|access[_-]?token|refresh[_-]?token)[A-Za-z_]*"

# Python m.fl.: en hemlighetsliknande nyckel som tilldelas en *strängliteral*.
# Tilldelningar av variabler, None eller funktionsanrop är inte hårdkodning och
# matchas därför inte - bara ett citerat värde är intressant.
SECRET_LITERAL = re.compile(
    rf"""(?ix)
    \b(?P<key>{SECRET_KEY})
    \s*(?::\s*[A-Za-z\[\]_.,\s]*)?     # valfri typannotering
    =\s*
    (?P<quote>["'])
    (?P<value>[^"'\n]*)
    (?P=quote)
    """,
)

# Konfigurationsfiler (.service, .env, .sql, .sh): KEY=värde utan citattecken.
SECRET_CONFIG = re.compile(rf"""(?ix)^\s*(?:Environment=\"?)?(?P<key>{SECRET_KEY})\s*=\s*(?P<value>[^\s"'\n]*)""")

# Kända icke-hemligheter. Matchas mot hela värdet, skiftlägesokänsligt.
ALLOWED_VALUES = re.compile(
    r"""(?ix)
    ^(
        |ollama                       # dummy som OpenAI-klienten kräver, Ollama ignorerar den
        |change_this_secure_password  # platshållare i init_mariadb_admin.sql
        |your_secure_password_here
        |%s|\?
        |<[^>]*>
    )$
    """,
)

# Hemligheter kortare än så är i praktiken alltid platshållare, inte riktiga
# uppgifter. Tröskeln håller nere falsklarmen utan att släppa igenom något
# som fungerar som lösenord.
MIN_SECRET_LENGTH = 6


def _scanned_files():
    for path in sorted(REPO_ROOT.rglob("*")):
        if not path.is_file():
            continue
        if any(part in SKIPPED_DIRS for part in path.relative_to(REPO_ROOT).parts):
            continue
        if path.name == Path(__file__).name:
            continue
        if path.suffix in SCANNED_SUFFIXES or path.name in SCANNED_EXTRA_NAMES:
            yield path


def _findings(path: Path):
    try:
        text = path.read_text(encoding="utf-8")
    except (UnicodeDecodeError, OSError):
        return
    rel = path.relative_to(REPO_ROOT)
    # Testfixturer använder medvetet påhittade uppgifter - skanna inte dem.
    if rel.parts and rel.parts[0] == "tests":
        return
    patterns = (SECRET_CONFIG,) if path.suffix != ".py" else (SECRET_LITERAL,)
    for lineno, line in enumerate(text.splitlines(), start=1):
        stripped = line.strip()
        if stripped.startswith("#") or stripped.startswith("--") or stripped.startswith("//"):
            continue
        for pattern in patterns:
            for match in pattern.finditer(line):
                value = match.group("value")
                if len(value) < MIN_SECRET_LENGTH or ALLOWED_VALUES.match(value):
                    continue
                # Rapportera plats och nyckel - aldrig själva värdet.
                yield f"{rel}:{lineno}: {match.group('key')}"


def test_no_hardcoded_credentials():
    """Inget källfilsvärde får se ut som ett inbakat lösenord eller en API-nyckel."""
    findings = [f for path in _scanned_files() for f in _findings(path)]
    assert not findings, (
        "Hårdkodade uppgifter hittade (värdena visas inte):\n  "
        + "\n  ".join(findings)
        + "\n\nLäs hemligheter via miljövariabler eller secret_store i stället."
    )


def test_env_example_has_no_password_value():
    """.env.example ska bara innehålla tomma platshållare."""
    example = REPO_ROOT / ".env.example"
    if not example.exists():
        pytest.skip(".env.example saknas")
    for lineno, line in enumerate(example.read_text(encoding="utf-8").splitlines(), start=1):
        stripped = line.strip()
        if stripped.startswith("#") or "=" not in stripped:
            continue
        key, _, value = stripped.partition("=")
        if "PASSWORD" in key.upper():
            assert value.strip() == "", f".env.example:{lineno} har ett ifyllt lösenord"


def test_service_file_has_no_inline_password():
    """systemd-enheten ska läsa lösenordet ur EnvironmentFile, inte Environment=."""
    unit = REPO_ROOT / "healthchat_web.service"
    if not unit.exists():
        pytest.skip("healthchat_web.service saknas")
    text = unit.read_text(encoding="utf-8")
    for lineno, line in enumerate(text.splitlines(), start=1):
        stripped = line.strip()
        if stripped.startswith("#"):
            continue
        if stripped.startswith("Environment=") and "PASSWORD" in stripped.upper():
            raise AssertionError(
                f"healthchat_web.service:{lineno} sätter ett lösenord inline. "
                "Använd EnvironmentFile= i stället."
            )
    assert "EnvironmentFile=" in text, "Enheten läser ingen EnvironmentFile"


def test_db_env_template_contains_no_credentials():
    """Mallen som skrivs till ~/.healthchat/db.env får inte innehålla värden."""
    import garmin_db

    for lineno, line in enumerate(garmin_db._DB_ENV_TEMPLATE.splitlines(), start=1):
        stripped = line.strip()
        if stripped.startswith("#") or not stripped:
            continue
        raise AssertionError(
            f"_DB_ENV_TEMPLATE rad {lineno} är inte utkommenterad - "
            "mallen får inte sätta några värden alls"
        )
