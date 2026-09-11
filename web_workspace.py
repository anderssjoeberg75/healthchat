"""Per-user runtime state for the web application.

The desktop build kept one ``HealthChatApp`` instance holding the settings, the
database, the source handlers, the AI client and the current conversation. The
web build needs the same pieces, but one set per logged-in account, so this
module owns a :class:`Workspace` per user.

Durable state lives in the encrypted per-user store (:mod:`web_store`); only
live objects — handlers, the AI client, the current chat and sync progress —
are held in memory.
"""

import logging
import threading
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import web_store
from ai_client import AIClient
from fitbit_handler import FitbitHandler
from garmin_db import GarminDatabase
from garmin_handler import GarminDataHandler
from strava_handler import StravaHandler
from withings_handler import WithingsDataHandler

logger = logging.getLogger("web_workspace")

# Where per-user OAuth/garth tokens are kept on the server. These are the files
# garth and the source handlers write; one directory per account keeps accounts
# from sharing a login.
USER_DATA_ROOT = Path.home() / ".healthchat" / "users"

DEFAULT_QUICK_QUESTIONS = [
    "🏋️‍♂️ Analysera min träning som min Personliga Tränare (PT)",
    "🏃‍♂️ Hur har mina löppass och tempo utvecklats?",
    "💤 Hur ser min sömn och återhämtning ut?",
    "🔥 Hur många kalorier har jag bränt denna vecka?",
]

# Mirrors the desktop config.json, minus the window geometry which has no
# meaning in a browser.
DEFAULT_SETTINGS: Dict[str, Any] = {
    "ai_provider": "xai",
    "xai_api_key": "",
    "xai_model": "grok-3",
    "openai_api_key": "",
    "openai_model": "gpt-4o",
    "azure_api_key": "",
    "azure_endpoint": "",
    "azure_deployment": "",
    "gemini_api_key": "",
    "gemini_model": "gemini-1.5-flash",
    "anthropic_api_key": "",
    "anthropic_model": "claude-sonnet-4-6",
    "ollama_model": "llama3.2",
    "ollama_base_url": "http://localhost:11434/v1",
    "garmin_email": "",
    "garmin_password": "",
    "withings_client_id": "",
    "withings_client_secret": "",
    "withings_refresh_token": "",
    "withings_access_token": "",
    "strava_client_id": "",
    "strava_client_secret": "",
    "strava_refresh_token": "",
    "strava_access_token": "",
    "fitbit_client_id": "",
    "fitbit_client_secret": "",
    "auto_login": True,
    "dark_mode": False,
    "days_range": 30,
}

# Never sent back to the browser; the UI only learns whether they are set.
SECRET_KEYS = {
    "garmin_password",
    "xai_api_key",
    "openai_api_key",
    "azure_api_key",
    "gemini_api_key",
    "anthropic_api_key",
    "withings_client_secret",
    "withings_refresh_token",
    "withings_access_token",
    "strava_client_secret",
    "strava_refresh_token",
    "strava_access_token",
    "fitbit_client_secret",
}

# Same migrations the desktop applied when loading its config file.
MODEL_MIGRATIONS = {
    "gemini-1.5-pro-latest": "gemini-1.5-pro",
    "gemini-1.5-flash-latest": "gemini-1.5-flash",
    "grok-beta": "grok-3",
    "grok-2-1212": "grok-3",
}
ANTHROPIC_MODEL_MIGRATIONS = {
    "claude-sonnet-4-5-20250929": "claude-sonnet-4-6",
    "claude-opus-4-5-20251101": "claude-opus-4-6",
    "claude-3-5-haiku-20241022": "claude-haiku-4-5-20251001",
}

SETTINGS_KEY = "web_settings"
PROMPTS_KEY = "web_saved_prompts"
QUICK_QUESTIONS_KEY = "web_quick_questions"
CHAT_INDEX_KEY = "web_chat_index"
CHAT_PREFIX = "web_chat:"


class Workspace:
    """Everything one account needs while it is logged in."""

    def __init__(self, user_id: int, session):
        self.user_id = user_id
        self.session = session
        self.lock = threading.RLock()

        self._db: Optional[GarminDatabase] = None

        self.dir = USER_DATA_ROOT / str(user_id)
        self.dir.mkdir(parents=True, exist_ok=True)
        self.token_dir = self.dir / "garmin_tokens"

        self.settings: Dict[str, Any] = dict(DEFAULT_SETTINGS)
        self._settings_loaded = False

        self.garmin_handler: Optional[GarminDataHandler] = None
        self.fitbit_handler = FitbitHandler(db=self.db(), token_store_dir=self.dir)
        self.strava_handler = StravaHandler(db=self.db(), token_store_dir=self.dir)
        self.ai_client: Optional[AIClient] = None

        self.authenticated = False
        self.mfa_required = False

        self.current_chat_history: List[Dict[str, Any]] = []
        self.conversation_context: List[Dict[str, Any]] = []
        self.max_context_messages = 10

        self.status = {"text": "⚪  Not connected", "is_error": False}
        self.sync_status = {"text": "", "running": False, "done": False}

    # --- database -----------------------------------------------------------

    def db(self) -> GarminDatabase:
        """A database handle bound to this user (and their encryption key).

        The handle is built once per workspace: each ``GarminDatabase()`` opens
        a fresh MariaDB pool, which is far too expensive to do per request.
        """
        with self.lock:
            if self._db is None:
                self._db = GarminDatabase()
            dek = getattr(self.session, "dek", None)
            if dek:
                self._db.set_user_session(self.user_id, bytes(dek))
            return self._db

    def refresh_session(self, session) -> None:
        """Adopt the current request's session (the DEK is what matters)."""
        self.session = session
        if self._db is not None:
            dek = getattr(session, "dek", None)
            if dek:
                self._db.set_user_session(self.user_id, bytes(dek))

    # --- settings -----------------------------------------------------------

    def load_settings(self, force: bool = False) -> Dict[str, Any]:
        if self._settings_loaded and not force:
            return self.settings

        stored = web_store.read(self.db(), self.session, SETTINGS_KEY, default={}) or {}
        merged = dict(DEFAULT_SETTINGS)
        if isinstance(stored, dict):
            merged.update(stored)

        if merged.get("anthropic_model") in ANTHROPIC_MODEL_MIGRATIONS:
            merged["anthropic_model"] = ANTHROPIC_MODEL_MIGRATIONS[merged["anthropic_model"]]
        for key in ("gemini_model", "xai_model"):
            if merged.get(key) in MODEL_MIGRATIONS:
                merged[key] = MODEL_MIGRATIONS[merged[key]]

        self.settings = merged
        self._settings_loaded = True
        return self.settings

    def save_settings(self) -> None:
        with self.lock:
            web_store.write(self.db(), self.session, SETTINGS_KEY, self.settings)

    def update_settings(self, values: Dict[str, Any]) -> Dict[str, Any]:
        self.load_settings()
        with self.lock:
            for key, value in (values or {}).items():
                if key not in DEFAULT_SETTINGS:
                    continue
                # An empty string for a secret means "keep what is stored".
                if key in SECRET_KEYS and value == "":
                    continue
                self.settings[key] = value
            self.save_settings()
        self.ai_client = None  # rebuilt with the new provider/key on next use
        return self.settings

    def public_settings(self) -> Dict[str, Any]:
        """Settings for the browser: secrets replaced by an "is set" flag."""
        self.load_settings()
        safe = {k: v for k, v in self.settings.items() if k not in SECRET_KEYS}
        safe["secrets_set"] = {k: bool(self.settings.get(k)) for k in SECRET_KEYS}
        return safe

    def get_user_profile(self) -> Dict[str, Any]:
        """Profile used for BMR, calorie burn and heart-rate zones."""
        profile = dict(getattr(self.session, "encrypted_profile", None) or {})
        return {
            "sex": profile.get("sex", "male") or "male",
            "height_cm": profile.get("height_cm", 0.0) or 0.0,
            "age": profile.get("age", 0) or 0,
            "weight_kg": profile.get("weight_kg", 0.0) or 0.0,
            "max_hr": profile.get("max_hr", 0) or 0,
        }

    # --- AI -----------------------------------------------------------------

    def get_current_ai_key(self) -> str:
        self.load_settings()
        provider = self.settings.get("ai_provider", "xai")
        if provider == "ollama":
            return "local"  # Ollama needs no key
        return self.settings.get(f"{provider}_api_key", "") or ""

    def initialize_ai_client(self) -> bool:
        """Build the AI client for the configured provider (desktop rules)."""
        self.load_settings()
        provider = self.settings.get("ai_provider", "xai")
        try:
            kwargs: Dict[str, Any] = {}
            if provider == "azure":
                kwargs["azure_endpoint"] = self.settings.get("azure_endpoint", "")
                kwargs["azure_deployment"] = self.settings.get("azure_deployment", "")
                model = self.settings.get("azure_deployment", "")
            elif provider == "ollama":
                kwargs["base_url"] = self.settings.get("ollama_base_url", "")
                model = self.settings.get("ollama_model", "llama3.2")
            else:
                model = self.settings.get(f"{provider}_model") or None

            self.ai_client = AIClient(
                provider=provider,
                api_key="" if provider == "ollama" else self.get_current_ai_key(),
                model=model,
                **kwargs,
            )
            return True
        except Exception as exc:
            logger.error("Could not initialize AI client for user %s: %s", self.user_id, exc)
            self.ai_client = None
            return False

    def ensure_ai_client(self) -> bool:
        return True if self.ai_client else self.initialize_ai_client()

    # --- data sources -------------------------------------------------------

    def build_garmin_handler(self) -> GarminDataHandler:
        self.load_settings()
        self.garmin_handler = GarminDataHandler(
            self.settings.get("garmin_email", ""),
            self.settings.get("garmin_password", ""),
            token_store_path=str(self.token_dir),
            db=self.db(),
        )
        return self.garmin_handler

    def restore_garmin_session(self) -> bool:
        """Re-use Garmin tokens stored on the server so a reload stays connected."""
        if self.authenticated and self.garmin_handler:
            return True
        self.load_settings()
        if not (self.settings.get("garmin_email") and self.settings.get("garmin_password")):
            return False
        if not any(self.token_dir.glob("oauth*token.json")):
            return False
        try:
            result = self.build_garmin_handler().authenticate()
            if result.get("success"):
                self.authenticated = True
                self.status = {"text": "✅ Connected to Garmin Connect!", "is_error": False}
                return True
        except Exception as exc:
            logger.info("Could not restore Garmin session for user %s: %s", self.user_id, exc)
        return False

    def withings_handler(self) -> Optional[WithingsDataHandler]:
        self.load_settings()
        if not (
            self.settings.get("withings_client_id")
            and self.settings.get("withings_client_secret")
            and self.settings.get("withings_refresh_token")
        ):
            return None
        return WithingsDataHandler(
            client_id=self.settings.get("withings_client_id", ""),
            client_secret=self.settings.get("withings_client_secret", ""),
            refresh_token=self.settings.get("withings_refresh_token", ""),
            access_token=self.settings.get("withings_access_token", ""),
            db=self.db(),
        )

    def sync_withings(self, days: int = 365, force_full: bool = False) -> Dict[str, Any]:
        """Sync Withings weight/body composition, persisting rotated tokens."""
        handler = self.withings_handler()
        if handler is None:
            return {"success": False, "error": "Saknar Withings OAuth2 credentials", "count": 0}
        try:
            result = handler.sync_withings_data(days=days, force_full=force_full)
            changed = False
            if result.get("access_token"):
                self.settings["withings_access_token"] = result["access_token"]
                changed = True
            if result.get("refresh_token"):
                self.settings["withings_refresh_token"] = result["refresh_token"]
                changed = True
            if changed:
                self.save_settings()
            return result
        except Exception as exc:
            logger.warning("Error syncing Withings data: %s", exc)
            return {"success": False, "error": str(exc), "count": 0}

    def connected_sources(self) -> Dict[str, bool]:
        self.load_settings()
        return {
            "garmin": bool(self.garmin_handler and self.authenticated),
            "fitbit": bool(self.fitbit_handler and self.fitbit_handler.is_authenticated()),
            "withings": bool(
                self.settings.get("withings_client_id")
                and self.settings.get("withings_client_secret")
                and self.settings.get("withings_refresh_token")
            ),
            "strava": bool(self.strava_handler and self.strava_handler.is_authenticated()),
        }

    # --- prompts and quick questions ---------------------------------------

    def load_quick_questions(self) -> List[str]:
        stored = web_store.read(self.db(), self.session, QUICK_QUESTIONS_KEY, default=None)
        if isinstance(stored, list) and stored:
            return stored[:8]
        return list(DEFAULT_QUICK_QUESTIONS)

    def save_quick_questions(self, questions: List[str]) -> List[str]:
        cleaned = [q.strip() for q in (questions or []) if q and q.strip()][:8]
        web_store.write(self.db(), self.session, QUICK_QUESTIONS_KEY, cleaned)
        return cleaned

    def load_saved_prompts(self) -> List[Dict[str, str]]:
        stored = web_store.read(self.db(), self.session, PROMPTS_KEY, default=[])
        return stored if isinstance(stored, list) else []

    def write_saved_prompts(self, prompts: List[Dict[str, str]]) -> None:
        web_store.write(self.db(), self.session, PROMPTS_KEY, prompts)

    # --- conversation -------------------------------------------------------

    def add_message(self, sender: str, message: str, kind: str = "user") -> Dict[str, Any]:
        entry = {
            "sender": sender,
            "message": message,
            "type": kind,
            "timestamp": datetime.now().strftime("%H:%M"),
        }
        self.current_chat_history.append(entry)
        return entry

    def reset_chat(self) -> None:
        self.current_chat_history = []
        self.conversation_context = []
        if self.ai_client:
            self.ai_client.reset_conversation()

    # --- saved conversations ------------------------------------------------

    def _chat_index(self) -> List[Dict[str, Any]]:
        stored = web_store.read(self.db(), self.session, CHAT_INDEX_KEY, default=[])
        return stored if isinstance(stored, list) else []

    def _write_chat_index(self, index: List[Dict[str, Any]]) -> None:
        web_store.write(self.db(), self.session, CHAT_INDEX_KEY, index)

    def list_saved_chats(self) -> List[Dict[str, Any]]:
        return sorted(self._chat_index(), key=lambda c: c.get("saved_at", ""), reverse=True)

    def read_saved_chat(self, chat_id: str) -> Optional[Dict[str, Any]]:
        entry = next((c for c in self._chat_index() if c.get("id") == chat_id), None)
        if entry is None:
            return None
        messages = web_store.read(self.db(), self.session, CHAT_PREFIX + chat_id, default=[])
        return {**entry, "messages": messages if isinstance(messages, list) else []}

    def save_current_chat(self, name: str) -> Dict[str, Any]:
        safe_name = (name or "").strip() or "Chat"
        chat_id = datetime.now().strftime("%Y%m%d_%H%M%S")
        entry = {
            "id": chat_id,
            "name": safe_name,
            "saved_at": datetime.now().isoformat(timespec="seconds"),
            "message_count": len(self.current_chat_history),
        }
        web_store.write(self.db(), self.session, CHAT_PREFIX + chat_id, self.current_chat_history)
        self._write_chat_index(self._chat_index() + [entry])
        return entry

    def rename_saved_chat(self, chat_id: str, new_name: str) -> bool:
        index = self._chat_index()
        for entry in index:
            if entry.get("id") == chat_id:
                entry["name"] = (new_name or "").strip() or entry.get("name", chat_id)
                self._write_chat_index(index)
                return True
        return False

    def delete_saved_chat(self, chat_id: str) -> bool:
        index = self._chat_index()
        remaining = [c for c in index if c.get("id") != chat_id]
        if len(remaining) == len(index):
            return False
        web_store.write(self.db(), self.session, CHAT_PREFIX + chat_id, [])
        self._write_chat_index(remaining)
        return True

    def search_chats(self, query: str) -> List[Dict[str, Any]]:
        """Search the current conversation and every saved one."""
        needle = (query or "").strip().lower()
        if not needle:
            return []

        hits: List[Dict[str, Any]] = []
        for message in self.current_chat_history:
            if needle in str(message.get("message", "")).lower():
                hits.append({"chat": "Nuvarande chatt", "chat_id": "", **message})

        for entry in self.list_saved_chats():
            chat = self.read_saved_chat(entry["id"]) or {}
            for message in chat.get("messages", []):
                if needle in str(message.get("message", "")).lower():
                    hits.append({"chat": entry.get("name", ""), "chat_id": entry["id"], **message})
        return hits


_workspaces: Dict[int, Workspace] = {}
_workspaces_lock = threading.Lock()


def get_workspace(session) -> Workspace:
    """The workspace for the session's user, created on first use."""
    user_id = session.user_id
    with _workspaces_lock:
        workspace = _workspaces.get(user_id)
        if workspace is None:
            workspace = Workspace(user_id, session)
            _workspaces[user_id] = workspace
        else:
            workspace.refresh_session(session)
        return workspace


def drop_workspace(user_id: int) -> None:
    with _workspaces_lock:
        _workspaces.pop(user_id, None)
