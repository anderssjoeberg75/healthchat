"""Per-user runtime state for the web application.

The desktop app kept one ``HealthChatApp`` instance holding the config, the
database, the source handlers, the AI client and the current conversation. The
web build keeps one :class:`Workspace` per logged-in user with exactly the same
pieces, so the behaviour of every feature is unchanged — only the owner of the
state differs.

Workspaces are cached in memory and created on demand; all durable state lives
under ``DATA_DIR/users/<id>/`` and survives a restart.
"""

import json
import logging
import sys
import threading
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from . import config

# The core modules (unchanged from the desktop build) live in the repo root.
sys.path.insert(0, str(config.PROJECT_ROOT))

from ai_client import AIClient  # noqa: E402
from fitbit_handler import FitbitHandler  # noqa: E402
from garmin_db import GarminDatabase  # noqa: E402
from garmin_handler import GarminDataHandler  # noqa: E402
from strava_handler import StravaHandler  # noqa: E402
from withings_handler import WithingsDataHandler  # noqa: E402

logger = logging.getLogger(__name__)

DEFAULT_QUICK_QUESTIONS = [
    "🏋️‍♂️ Analysera min träning som min Personliga Tränare (PT)",
    "🏃‍♂️ Hur har mina löppass och tempo utvecklats?",
    "💤 Hur ser min sömn och återhämtning ut?",
    "🔥 Hur många kalorier har jag bränt denna vecka?",
]

# Keys that hold credentials. They are never sent to the browser in clear text.
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

DEFAULT_CONFIG: Dict[str, Any] = {
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
    "user_sex": "male",
    "user_height_cm": 0.0,
    "user_age": 0,
    "user_weight_kg": 0.0,
    "auto_login": True,
    "dark_mode": False,
    "days_range": 30,
}

# Same migrations the desktop build applied when loading its config file.
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


class Workspace:
    """Everything one user needs: config, database, handlers, AI client, chat."""

    def __init__(self, user_id: int):
        self.user_id = user_id
        self.lock = threading.RLock()

        self.dir = config.user_dir(user_id)
        self.config_file = self.dir / "config.json"
        self.saved_prompts_file = self.dir / "saved_prompts.json"
        self.quick_questions_file = self.dir / "quick_questions.json"
        self.chat_history_dir = self.dir / "chat_history"
        self.chat_history_dir.mkdir(exist_ok=True)
        self.token_dir = self.dir / "garmin_tokens"

        self.db = GarminDatabase(db_path=self.dir / "healthdata.db")
        self.config: Dict[str, Any] = {}
        self.load_config()

        self.garmin_handler: Optional[GarminDataHandler] = None
        self.fitbit_handler = FitbitHandler(db=self.db, token_store_dir=self.dir)
        self.strava_handler = StravaHandler(db=self.db, token_store_dir=self.dir)
        self.ai_client: Optional[AIClient] = None

        self.authenticated = False
        self.mfa_required = False

        # Current conversation (mirrors the desktop's in-memory chat state).
        self.current_chat_history: List[Dict[str, Any]] = []
        self.conversation_context: List[Dict[str, Any]] = []
        self.max_context_messages = 10

        self.status = {"text": "⚪  Not connected", "is_error": False}
        self.sync_status = {"text": "", "running": False, "done": False}

    # --- configuration -----------------------------------------------------

    def load_config(self) -> None:
        merged = dict(DEFAULT_CONFIG)
        try:
            if self.config_file.exists():
                with open(self.config_file, "r", encoding="utf-8") as handle:
                    merged.update(json.load(handle))
        except Exception as exc:  # A corrupt file must not lock the user out.
            logger.error("Could not read config for user %s: %s", self.user_id, exc)

        if merged.get("anthropic_model") in ANTHROPIC_MODEL_MIGRATIONS:
            merged["anthropic_model"] = ANTHROPIC_MODEL_MIGRATIONS[merged["anthropic_model"]]
        for key in ("gemini_model", "xai_model"):
            if merged.get(key) in MODEL_MIGRATIONS:
                merged[key] = MODEL_MIGRATIONS[merged[key]]

        self.config = merged

    def save_config(self) -> None:
        with self.lock:
            tmp = self.config_file.with_suffix(".json.tmp")
            with open(tmp, "w", encoding="utf-8") as handle:
                json.dump(self.config, handle, indent=2, ensure_ascii=False)
            tmp.replace(self.config_file)
            try:
                self.config_file.chmod(0o600)
            except OSError:
                pass

    def update_config(self, values: Dict[str, Any]) -> None:
        with self.lock:
            for key, value in values.items():
                if key not in DEFAULT_CONFIG:
                    continue
                # An empty string for a secret means "keep what is stored".
                if key in SECRET_KEYS and value == "":
                    continue
                self.config[key] = value
            self.save_config()
        self.ai_client = None  # Rebuilt with the new provider/key on next use.

    def public_config(self) -> Dict[str, Any]:
        """Config for the browser: secrets replaced by a "is set" flag."""
        safe = {k: v for k, v in self.config.items() if k not in SECRET_KEYS}
        safe["secrets_set"] = {k: bool(self.config.get(k)) for k in SECRET_KEYS}
        return safe

    def get_user_profile(self) -> Dict[str, Any]:
        return {
            "sex": self.config.get("user_sex", "male"),
            "height_cm": self.config.get("user_height_cm", 0.0),
            "age": self.config.get("user_age", 0),
            "weight_kg": self.config.get("user_weight_kg", 0.0),
        }

    # --- AI ----------------------------------------------------------------

    def get_current_ai_key(self) -> str:
        provider = self.config.get("ai_provider", "xai")
        if provider == "ollama":
            return "local"  # Ollama needs no key.
        return self.config.get(f"{provider}_api_key", "") or ""

    def initialize_ai_client(self) -> bool:
        """Create the AI client for the configured provider (same rules as desktop)."""
        provider = self.config.get("ai_provider", "xai")
        try:
            kwargs: Dict[str, Any] = {}
            if provider == "azure":
                kwargs["azure_endpoint"] = self.config.get("azure_endpoint", "")
                kwargs["azure_deployment"] = self.config.get("azure_deployment", "")
                model = self.config.get("azure_deployment", "")
            elif provider == "ollama":
                kwargs["base_url"] = self.config.get("ollama_base_url", "")
                model = self.config.get("ollama_model", "llama3.2")
            else:
                model = self.config.get(f"{provider}_model") or None

            self.ai_client = AIClient(
                provider=provider,
                api_key=self.get_current_ai_key() if provider != "ollama" else "",
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

    # --- data sources ------------------------------------------------------

    def build_garmin_handler(self) -> GarminDataHandler:
        self.garmin_handler = GarminDataHandler(
            self.config.get("garmin_email", ""),
            self.config.get("garmin_password", ""),
            token_store_path=str(self.token_dir),
            db=self.db,
        )
        return self.garmin_handler

    def restore_garmin_session(self) -> bool:
        """Re-use Garmin tokens stored on the server so a browser reload stays connected."""
        if self.authenticated and self.garmin_handler:
            return True
        if not (self.config.get("garmin_email") and self.config.get("garmin_password")):
            return False
        if not any(self.token_dir.glob("oauth*token.json")):
            return False
        try:
            handler = self.build_garmin_handler()
            result = handler.authenticate()
            if result.get("success"):
                self.authenticated = True
                self.status = {"text": "✅ Connected to Garmin Connect!", "is_error": False}
                return True
        except Exception as exc:
            logger.info("Could not restore Garmin session for user %s: %s", self.user_id, exc)
        return False

    def withings_handler(self) -> Optional[WithingsDataHandler]:
        if not (self.config.get("withings_client_id") and self.config.get("withings_client_secret")
                and self.config.get("withings_refresh_token")):
            return None
        return WithingsDataHandler(
            client_id=self.config.get("withings_client_id", ""),
            client_secret=self.config.get("withings_client_secret", ""),
            refresh_token=self.config.get("withings_refresh_token", ""),
            access_token=self.config.get("withings_access_token", ""),
            db=self.db,
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
                self.config["withings_access_token"] = result["access_token"]
                changed = True
            if result.get("refresh_token"):
                self.config["withings_refresh_token"] = result["refresh_token"]
                changed = True
            if changed:
                self.save_config()
            return result
        except Exception as exc:
            logger.warning("Error syncing Withings data: %s", exc)
            return {"success": False, "error": str(exc), "count": 0}

    def connected_sources(self) -> Dict[str, bool]:
        return {
            "garmin": bool(self.garmin_handler and self.authenticated),
            "fitbit": bool(self.fitbit_handler and self.fitbit_handler.is_authenticated()),
            "withings": bool(
                self.config.get("withings_client_id")
                and self.config.get("withings_client_secret")
                and self.config.get("withings_refresh_token")
            ),
            "strava": bool(self.strava_handler and self.strava_handler.is_authenticated()),
        }

    # --- prompts, quick questions, chat history -----------------------------

    def load_quick_questions(self) -> List[str]:
        try:
            if self.quick_questions_file.exists():
                with open(self.quick_questions_file, "r", encoding="utf-8") as handle:
                    questions = json.load(handle)
                if isinstance(questions, list) and questions:
                    return questions[:8]
        except Exception as exc:
            logger.error("Error loading quick questions: %s", exc)
        return list(DEFAULT_QUICK_QUESTIONS)

    def save_quick_questions(self, questions: List[str]) -> List[str]:
        cleaned = [q.strip() for q in questions if q and q.strip()][:8]
        with open(self.quick_questions_file, "w", encoding="utf-8") as handle:
            json.dump(cleaned, handle, indent=2, ensure_ascii=False)
        return cleaned

    def load_saved_prompts(self) -> List[Dict[str, str]]:
        try:
            if self.saved_prompts_file.exists():
                with open(self.saved_prompts_file, "r", encoding="utf-8") as handle:
                    prompts = json.load(handle)
                return prompts if isinstance(prompts, list) else []
        except Exception as exc:
            logger.error("Error loading saved prompts: %s", exc)
        return []

    def write_saved_prompts(self, prompts: List[Dict[str, str]]) -> None:
        with open(self.saved_prompts_file, "w", encoding="utf-8") as handle:
            json.dump(prompts, handle, indent=2, ensure_ascii=False)

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

    def list_saved_chats(self) -> List[Dict[str, Any]]:
        chats = []
        for path in sorted(self.chat_history_dir.glob("*.json"), reverse=True):
            try:
                with open(path, "r", encoding="utf-8") as handle:
                    data = json.load(handle)
                messages = data.get("messages", data if isinstance(data, list) else [])
                chats.append(
                    {
                        "id": path.stem,
                        "name": data.get("name", path.stem) if isinstance(data, dict) else path.stem,
                        "saved_at": data.get("saved_at", "") if isinstance(data, dict) else "",
                        "message_count": len(messages),
                    }
                )
            except Exception as exc:
                logger.warning("Skipping unreadable chat file %s: %s", path.name, exc)
        return chats

    def read_saved_chat(self, chat_id: str) -> Optional[Dict[str, Any]]:
        path = self._chat_path(chat_id)
        if not path or not path.exists():
            return None
        with open(path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
        if isinstance(data, list):
            data = {"name": path.stem, "messages": data}
        data["id"] = path.stem
        return data

    def save_current_chat(self, name: str) -> Dict[str, Any]:
        safe_name = "".join(c for c in (name or "").strip() if c.isalnum() or c in " -_åäöÅÄÖ").strip()
        safe_name = safe_name or "Chat"
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        path = self.chat_history_dir / f"{safe_name}_{stamp}.json"
        payload = {
            "name": safe_name,
            "saved_at": datetime.now().isoformat(timespec="seconds"),
            "messages": self.current_chat_history,
        }
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, ensure_ascii=False)
        payload["id"] = path.stem
        return payload

    def delete_saved_chat(self, chat_id: str) -> bool:
        path = self._chat_path(chat_id)
        if path and path.exists():
            path.unlink()
            return True
        return False

    def rename_saved_chat(self, chat_id: str, new_name: str) -> bool:
        data = self.read_saved_chat(chat_id)
        if data is None:
            return False
        data["name"] = (new_name or "").strip() or data.get("name", chat_id)
        path = self._chat_path(chat_id)
        with open(path, "w", encoding="utf-8") as handle:
            json.dump({k: v for k, v in data.items() if k != "id"}, handle, indent=2, ensure_ascii=False)
        return True

    def search_chats(self, query: str) -> List[Dict[str, Any]]:
        """Search saved conversations and the live one (same scope as the desktop dialog)."""
        needle = (query or "").strip().lower()
        if not needle:
            return []
        hits: List[Dict[str, Any]] = []
        for message in self.current_chat_history:
            if needle in str(message.get("message", "")).lower():
                hits.append({"chat": "Nuvarande chatt", "chat_id": "", **message})
        for chat in self.list_saved_chats():
            data = self.read_saved_chat(chat["id"]) or {}
            for message in data.get("messages", []):
                if needle in str(message.get("message", "")).lower():
                    hits.append({"chat": chat["name"], "chat_id": chat["id"], **message})
        return hits

    def _chat_path(self, chat_id: str) -> Optional[Path]:
        # Guard against path traversal from a crafted chat id.
        candidate = (self.chat_history_dir / f"{chat_id}.json").resolve()
        if candidate.parent != self.chat_history_dir.resolve():
            return None
        return candidate


_workspaces: Dict[int, Workspace] = {}
_workspaces_lock = threading.Lock()


def get_workspace(user_id: int) -> Workspace:
    with _workspaces_lock:
        workspace = _workspaces.get(user_id)
        if workspace is None:
            workspace = Workspace(user_id)
            _workspaces[user_id] = workspace
        return workspace


def drop_workspace(user_id: int) -> None:
    with _workspaces_lock:
        _workspaces.pop(user_id, None)
