"""Runtime configuration for the HealthChat web application.

Everything that used to live in ``~/.healthchat`` on a single desktop machine is
now scoped per user underneath :data:`DATA_DIR` on the server. Nothing here is
user specific; per-user paths are resolved in :mod:`webapp.backend.workspace`.
"""

import os
import secrets
from pathlib import Path

APP_VERSION = "5.0.0"

# Root of the repository (the shared core modules live here).
PROJECT_ROOT = Path(__file__).resolve().parents[2]

# Where all server-side user data is stored (databases, tokens, chat history).
DATA_DIR = Path(os.environ.get("HEALTHCHAT_DATA_DIR", PROJECT_ROOT / "data")).resolve()

# Public base URL of the deployment, used to build OAuth redirect URIs.
BASE_URL = os.environ.get("HEALTHCHAT_BASE_URL", "http://localhost:8000").rstrip("/")

# Cookie signing / session secret. Generated and persisted on first start so a
# restart does not log everyone out.
_SECRET_FILE = DATA_DIR / "secret_key"


def _load_secret_key() -> str:
    env_secret = os.environ.get("HEALTHCHAT_SECRET_KEY")
    if env_secret:
        return env_secret
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    if _SECRET_FILE.exists():
        return _SECRET_FILE.read_text(encoding="utf-8").strip()
    secret = secrets.token_urlsafe(48)
    _SECRET_FILE.write_text(secret, encoding="utf-8")
    try:
        _SECRET_FILE.chmod(0o600)
    except OSError:
        pass
    return secret


SECRET_KEY = _load_secret_key()

SESSION_COOKIE = "healthchat_session"
SESSION_TTL_DAYS = int(os.environ.get("HEALTHCHAT_SESSION_TTL_DAYS", "30"))

# Set to "1" to disable self-service registration (invite-only deployments).
REGISTRATION_DISABLED = os.environ.get("HEALTHCHAT_DISABLE_REGISTRATION", "") == "1"

# Only send the session cookie over HTTPS. Enable in production.
COOKIE_SECURE = os.environ.get("HEALTHCHAT_COOKIE_SECURE", "") == "1"

USERS_DB = DATA_DIR / "users.db"
USER_DATA_DIR = DATA_DIR / "users"

FRONTEND_DIR = Path(__file__).resolve().parents[1] / "frontend"


def user_dir(user_id: int) -> Path:
    """Per-user data directory (mirrors the old ``~/.healthchat`` layout)."""
    path = USER_DATA_DIR / str(user_id)
    path.mkdir(parents=True, exist_ok=True)
    return path
