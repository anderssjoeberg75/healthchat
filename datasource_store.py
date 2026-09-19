"""
Datasource Store for HealthChat Web.

Per-user encrypted storage of external service credentials and OAuth tokens for
the four supported data sources (Strava, Garmin Connect, Withings, Fitbit), plus
handler factories and a synchronous sync dispatcher used by the web API.

Design notes:
- The desktop app (temp/HealthChatDesktop.py) keeps a single set of credentials in
  a local config file + OS keyring. That model is single user only, so the web
  layer stores one row per (user_id, provider) in `user_datasources`, encrypted
  with the logged-in user's DEK exactly like the health data tables (S-13).
- The handlers (strava_handler, fitbit_handler, garmin_handler) persist tokens to
  disk/keyring on their own. To keep users isolated they are always instantiated
  against a throwaway temp directory, which is removed once the operation ends.
  The authoritative copy of the tokens lives in the encrypted database row.
"""

import os
import json
import shutil
import logging
import tempfile
import threading
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

import crypto

logger = logging.getLogger("datasource_store")

TABLE_NAME = "user_datasources"

# Provider catalogue. `steps` mirrors the instructions shown in the desktop
# dialogs (FitbitConnectDialog, StravaConnectDialog, WithingsConnectDialog,
# GarminConnectDialog) but adapted to the web callback URL.
PROVIDERS: Dict[str, Dict[str, Any]] = {
    "strava": {
        "name": "Strava",
        "icon": "🏃",
        "color": "#FC4C02",
        "auth_kind": "oauth",
        "description": "Hämtar träningspass (aktiviteter) med distans, tid och puls samt atletprofil.",
        "portal_url": "https://www.strava.com/settings/api",
        "portal_label": "Öppna Strava API-inställningar (strava.com/settings/api)",
        "steps": [
            "Öppna länken nedan och logga in med ditt Strava-konto.",
            "Skapa (eller öppna) din API-applikation under \"My API Application\".",
            "Sätt Authorization Callback Domain till domänen i Callback-URL:en nedan.",
            "Kopiera Client ID och Client Secret och klistra in dem här.",
            "Spara uppgifterna och klicka därefter på Anslut för att godkänna åtkomsten.",
        ],
        "sync_days": 3650,
        "sync_label": "aktiviteter",
    },
    "garmin": {
        "name": "Garmin Connect",
        "icon": "⌚",
        "color": "#0078D4",
        "auth_kind": "credentials",
        "description": "Hämtar dagsdata, sömn, HRV, stress, Body Battery och aktiviteter från Garmin Connect.",
        "portal_url": "https://connect.garmin.com/",
        "portal_label": "Öppna Garmin Connect (connect.garmin.com)",
        "steps": [
            "Ange e-postadress och lösenord för ditt Garmin Connect-konto.",
            "Uppgifterna skickas via TLS till Garmin och lagras krypterade med din egen nyckel.",
            "Har du tvåfaktorsinloggning (MFA) aktiverad visas ett fält för engångskoden.",
            "Efter anslutningen sparas sessionstokens så att inloggningen kan återanvändas.",
        ],
        "sync_days": 30,
        "sync_label": "dagar",
    },
    "withings": {
        "name": "Withings Health Mate",
        "icon": "⚖️",
        "color": "#10B981",
        "auth_kind": "oauth",
        "description": "Hämtar vikt och kroppssammansättning (fett, muskler, skelett, vatten, BMI).",
        "portal_url": "https://developer.withings.com/dashboard/",
        "portal_label": "Öppna Withings Developer Portal (developer.withings.com/dashboard)",
        "steps": [
            "Öppna länken nedan och logga in på Withings utvecklarportal.",
            "Skapa en applikation och ange Callback-URL:en nedan exakt som den står.",
            "Kopiera Client ID och Client Secret och klistra in dem här.",
            "Spara uppgifterna och klicka därefter på Anslut för att godkänna åtkomsten.",
        ],
        "sync_days": 365,
        "sync_label": "mätvärden",
    },
    "fitbit": {
        "name": "Fitbit",
        "icon": "⌚",
        "color": "#00B0B9",
        "auth_kind": "oauth",
        "description": "Hämtar sömn, puls, steg och vikt från ditt Fitbit-konto.",
        "portal_url": "https://dev.fitbit.com/apps",
        "portal_label": "Öppna Fitbit Developer Portal (dev.fitbit.com/apps)",
        "steps": [
            "Öppna länken nedan, logga in och klicka på \"Register a New App\".",
            "Application Type: Personal och Default Access Type: Read-Only räcker.",
            "Ange Callback-URL:en nedan exakt som den står i fältet Redirect URL.",
            "Spara appen och kopiera OAuth 2.0 Client ID och Client Secret hit.",
            "Spara uppgifterna och klicka därefter på Anslut för att godkänna åtkomsten.",
        ],
        "sync_days": 30,
        "sync_label": "dagar",
    },
    "whoop": {
        "name": "Whoop",
        "icon": "⚡",
        "color": "#111827",
        "auth_kind": "oauth",
        "description": "Hämtar återhämtning (Recovery), sömn, dagsbelastning (Strain) och träningspass från Whoop.",
        "portal_url": "https://developer-dashboard.whoop.com/",
        "portal_label": "Öppna Whoop Developer Dashboard (developer-dashboard.whoop.com)",
        "steps": [
            "Öppna länken nedan och logga in på Whoop Developer Dashboard.",
            "Skapa en applikation under \"Create An App\".",
            "Ange Callback-URL:en nedan exakt som Redirect URI i din app.",
            "Kopiera Client ID och Client Secret och klistra in dem här.",
            "Spara uppgifterna och klicka därefter på Anslut för att godkänna åtkomsten.",
        ],
        "sync_days": 30,
        "sync_label": "mätvärden",
    },
}

PROVIDER_ORDER: List[str] = ["strava", "garmin", "withings", "fitbit", "whoop"]

# garth keeps its authenticated client in module state, so every Garmin login is
# serialized through this lock. Data fetching afterwards still goes through that
# shared client, which is why the web layer runs with a single worker process.
GARMIN_AUTH_LOCK = threading.Lock()

# Payload keys that must never leave the server in an API response.
SECRET_FIELDS = (
    "client_secret",
    "password",
    "access_token",
    "refresh_token",
    "code_verifier",
    "oauth_state",
    "garmin_tokens",
    "oauth1_token",
    "oauth2_token",
)


def is_valid_provider(provider: str) -> bool:
    return provider in PROVIDERS


# --- DATABASE LAYER ---------------------------------------------------------

def _is_mariadb(conn) -> bool:
    return hasattr(conn, "ping")


def _ph(conn) -> str:
    return "%s" if _is_mariadb(conn) else "?"


def _table(conn) -> str:
    return f"`{TABLE_NAME}`" if _is_mariadb(conn) else TABLE_NAME


@contextmanager
def _cursor(conn):
    cur = conn.cursor()
    try:
        yield cur
    finally:
        try:
            cur.close()
        except Exception:
            pass


def _users_id_column_type(conn) -> str:
    """
    Data type of users.id in the live MariaDB schema.

    Existing deployments were created by garmin_db's own migration path, where
    users.id is int(11), while init_mariadb.sql declares BIGINT. A foreign key
    only forms when the types match exactly, so the type is read back instead of
    assumed.
    """
    try:
        with _cursor(conn) as cur:
            cur.execute(
                "SELECT COLUMN_TYPE FROM information_schema.COLUMNS "
                "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'users' AND COLUMN_NAME = 'id'"
            )
            row = cur.fetchone()
        if row:
            col_type = _row_value(row, "COLUMN_TYPE", 0)
            if col_type:
                if isinstance(col_type, (bytes, bytearray)):
                    col_type = col_type.decode("utf-8", "ignore")
                return str(col_type)
    except Exception as e:
        logger.debug(f"Could not read users.id column type: {e}")
    return "BIGINT"


def ensure_table(conn) -> None:
    """Create the user_datasources table if it does not exist."""
    if not _is_mariadb(conn):
        with _cursor(conn) as cur:
            cur.execute(
                f"""
                CREATE TABLE IF NOT EXISTS {TABLE_NAME} (
                    user_id INTEGER NOT NULL,
                    provider TEXT NOT NULL,
                    encrypted_payload BLOB NOT NULL,
                    nonce BLOB NOT NULL,
                    connected INTEGER NOT NULL DEFAULT 0,
                    last_sync_at TEXT,
                    last_sync_count INTEGER NOT NULL DEFAULT 0,
                    updated_at TEXT,
                    PRIMARY KEY (user_id, provider)
                )
                """
            )
        if hasattr(conn, "commit"):
            conn.commit()
        return

    user_id_type = _users_id_column_type(conn)
    columns = f"""
            user_id {user_id_type} NOT NULL,
            provider VARCHAR(32) NOT NULL,
            encrypted_payload LONGBLOB NOT NULL,
            nonce VARBINARY(32) NOT NULL,
            connected TINYINT(1) NOT NULL DEFAULT 0,
            last_sync_at DATETIME NULL,
            last_sync_count INT NOT NULL DEFAULT 0,
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (user_id, provider)"""
    suffix = ") ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci"

    with_fk = (
        f"CREATE TABLE IF NOT EXISTS `{TABLE_NAME}` ({columns},\n"
        f"            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE\n{suffix}"
    )
    without_fk = f"CREATE TABLE IF NOT EXISTS `{TABLE_NAME}` ({columns}\n{suffix}"

    try:
        with _cursor(conn) as cur:
            cur.execute(with_fk)
    except Exception as fk_error:
        # Without the cascade, auth.delete_user_account still removes these rows explicitly.
        logger.warning(f"Creating {TABLE_NAME} without foreign key ({fk_error})")
        with _cursor(conn) as cur:
            cur.execute(without_fk)

    if hasattr(conn, "commit"):
        conn.commit()


def _row_value(row, key: str, index: int):
    if row is None:
        return None
    if isinstance(row, dict):
        return row.get(key)
    return row[index]


def load_record(conn, user_id: int, dek: bytes, provider: str) -> Dict[str, Any]:
    """Load and decrypt one datasource row. Returns an empty record when missing."""
    if not is_valid_provider(provider):
        raise ValueError(f"Okänd datakälla: {provider}")

    empty = {
        "payload": {},
        "connected": False,
        "last_sync_at": None,
        "last_sync_count": 0,
        "exists": False,
    }
    if conn is None or not dek:
        return empty

    ph = _ph(conn)
    try:
        with _cursor(conn) as cur:
            cur.execute(
                f"SELECT encrypted_payload, nonce, connected, last_sync_at, last_sync_count "
                f"FROM {_table(conn)} WHERE user_id = {ph} AND provider = {ph}",
                (user_id, provider),
            )
            row = cur.fetchone()
    except Exception as e:
        logger.warning(f"Could not read datasource row for provider {provider}: {e}")
        return empty

    if not row:
        return empty

    payload: Dict[str, Any] = {}
    try:
        decoded = crypto.decrypt_payload(
            bytes(dek),
            bytes(_row_value(row, "encrypted_payload", 0) or b""),
            bytes(_row_value(row, "nonce", 1) or b""),
        )
        if isinstance(decoded, dict):
            payload = decoded
    except Exception as e:
        logger.error(f"Failed to decrypt datasource payload for {provider}: {e}")

    last_sync = _row_value(row, "last_sync_at", 3)
    if isinstance(last_sync, datetime):
        last_sync = last_sync.isoformat(sep=" ", timespec="seconds")

    return {
        "payload": payload,
        "connected": bool(_row_value(row, "connected", 2)),
        "last_sync_at": last_sync,
        "last_sync_count": int(_row_value(row, "last_sync_count", 4) or 0),
        "exists": True,
    }


def save_record(
    conn,
    user_id: int,
    dek: bytes,
    provider: str,
    payload: Dict[str, Any],
    connected: Optional[bool] = None,
    last_sync_at: Optional[str] = None,
    last_sync_count: Optional[int] = None,
) -> None:
    """Encrypt and upsert one datasource row, preserving unspecified metadata."""
    if not is_valid_provider(provider):
        raise ValueError(f"Okänd datakälla: {provider}")
    if conn is None or not dek:
        raise RuntimeError("Ingen databasanslutning eller krypteringsnyckel tillgänglig.")

    existing = load_record(conn, user_id, dek, provider)
    final_connected = existing["connected"] if connected is None else bool(connected)
    final_sync_at = existing["last_sync_at"] if last_sync_at is None else last_sync_at
    final_sync_count = existing["last_sync_count"] if last_sync_count is None else int(last_sync_count)

    clean_payload = {k: v for k, v in (payload or {}).items() if v not in (None, "")}
    nonce, ciphertext = crypto.encrypt_payload(bytes(dek), clean_payload)

    ph = _ph(conn)
    table = _table(conn)
    with _cursor(conn) as cur:
        cur.execute(f"DELETE FROM {table} WHERE user_id = {ph} AND provider = {ph}", (user_id, provider))
        cur.execute(
            f"INSERT INTO {table} "
            f"(user_id, provider, encrypted_payload, nonce, connected, last_sync_at, last_sync_count, updated_at) "
            f"VALUES ({ph}, {ph}, {ph}, {ph}, {ph}, {ph}, {ph}, {ph})",
            (
                user_id,
                provider,
                ciphertext,
                nonce,
                1 if final_connected else 0,
                final_sync_at,
                final_sync_count,
                datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            ),
        )
    if hasattr(conn, "commit"):
        conn.commit()


def delete_record(conn, user_id: int, provider: str) -> None:
    """Remove all stored credentials and tokens for one provider."""
    if not is_valid_provider(provider):
        raise ValueError(f"Okänd datakälla: {provider}")
    if conn is None:
        return
    ph = _ph(conn)
    with _cursor(conn) as cur:
        cur.execute(f"DELETE FROM {_table(conn)} WHERE user_id = {ph} AND provider = {ph}", (user_id, provider))
    if hasattr(conn, "commit"):
        conn.commit()


def public_status(provider: str, record: Dict[str, Any], callback_url: str = "") -> Dict[str, Any]:
    """Build the API-safe status object for one provider (never exposes secrets)."""
    meta = PROVIDERS[provider]
    payload = record.get("payload") or {}

    if meta["auth_kind"] == "oauth":
        has_credentials = bool(payload.get("client_id") and payload.get("client_secret"))
    else:
        has_credentials = bool(payload.get("email") and payload.get("password"))

    return {
        "provider": provider,
        "name": meta["name"],
        "icon": meta["icon"],
        "color": meta["color"],
        "auth_kind": meta["auth_kind"],
        "description": meta["description"],
        "portal_url": meta["portal_url"],
        "portal_label": meta["portal_label"],
        "steps": meta["steps"],
        "sync_label": meta["sync_label"],
        "callback_url": callback_url,
        "connected": bool(record.get("connected")),
        "has_credentials": has_credentials,
        "client_id": payload.get("client_id", ""),
        "email": payload.get("email", ""),
        "secret_set": bool(payload.get("client_secret") or payload.get("password")),
        "last_sync_at": record.get("last_sync_at"),
        "last_sync_count": record.get("last_sync_count", 0),
    }


def list_status(conn, user_id: int, dek: bytes, callback_url_for: Callable[[str], str]) -> List[Dict[str, Any]]:
    """Return API-safe status for every provider in display order."""
    out: List[Dict[str, Any]] = []
    for provider in PROVIDER_ORDER:
        try:
            record = load_record(conn, user_id, dek, provider)
        except Exception as e:
            logger.warning(f"Could not load status for {provider}: {e}")
            record = {"payload": {}, "connected": False, "last_sync_at": None, "last_sync_count": 0}
        out.append(public_status(provider, record, callback_url_for(provider)))
    return out


# --- HANDLER FACTORIES ------------------------------------------------------

@contextmanager
def temp_token_dir():
    """Throwaway token directory so handler disk writes never leak between users."""
    path = Path(tempfile.mkdtemp(prefix="healthchat_ds_"))
    try:
        yield path
    finally:
        shutil.rmtree(path, ignore_errors=True)


def build_handler(provider: str, db, payload: Dict[str, Any], token_dir: Path) -> Any:
    """Instantiate the provider handler, hydrated from the stored payload."""
    if provider == "strava":
        from strava_handler import StravaHandler
        handler = StravaHandler(db=db, token_store_dir=token_dir)
        handler.client_id = payload.get("client_id") or None
        handler.client_secret = payload.get("client_secret") or None
        handler.access_token = payload.get("access_token") or None
        handler.refresh_token = payload.get("refresh_token") or None
        handler.expires_at = payload.get("expires_at")
        handler.current_state = payload.get("oauth_state")
        handler._authenticated = bool(handler.access_token)
        return handler

    if provider == "fitbit":
        from fitbit_handler import FitbitHandler
        handler = FitbitHandler(db=db, token_store_dir=token_dir)
        handler.client_id = payload.get("client_id") or None
        handler.client_secret = payload.get("client_secret") or None
        handler.access_token = payload.get("access_token") or None
        handler.refresh_token = payload.get("refresh_token") or None
        handler.expires_at = payload.get("expires_at")
        handler.current_state = payload.get("oauth_state")
        handler.code_verifier = payload.get("code_verifier")
        handler._authenticated = bool(handler.access_token)
        return handler

    if provider == "withings":
        from withings_handler import WithingsDataHandler
        handler = WithingsDataHandler(
            client_id=payload.get("client_id", "") or "",
            client_secret=payload.get("client_secret", "") or "",
            refresh_token=payload.get("refresh_token", "") or "",
            access_token=payload.get("access_token", "") or "",
            db=db,
        )
        handler.current_state = payload.get("oauth_state")
        return handler

    if provider == "whoop":
        from whoop_handler import WhoopHandler
        handler = WhoopHandler(db=db, token_store_dir=token_dir)
        handler.client_id = payload.get("client_id") or None
        handler.client_secret = payload.get("client_secret") or None
        handler.access_token = payload.get("access_token") or None
        handler.refresh_token = payload.get("refresh_token") or None
        handler.expires_at = payload.get("expires_at")
        handler.current_state = payload.get("oauth_state")
        handler._authenticated = bool(handler.access_token)
        return handler

    if provider == "garmin":
        from garmin_handler import GarminDataHandler
        for name in ("garmin_tokens", "oauth1_token", "oauth2_token"):
            raw = payload.get(name)
            if not raw:
                continue
            try:
                data = raw if isinstance(raw, dict) else json.loads(raw)
                token_path = token_dir / f"{name}.json"
                fd = os.open(str(token_path), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
                with os.fdopen(fd, "w", encoding="utf-8") as f:
                    json.dump(data, f)
            except Exception as e:
                logger.warning(f"Could not materialise Garmin {name}: {e}")
        return GarminDataHandler(
            email=payload.get("email", "") or "",
            password=payload.get("password", "") or "",
            token_store_path=str(token_dir),
            db=db,
        )

    raise ValueError(f"Okänd datakälla: {provider}")


def collect_tokens(provider: str, handler, token_dir: Optional[Path] = None) -> Dict[str, Any]:
    """Read back the tokens a handler ended up holding, for encrypted persistence."""
    tokens: Dict[str, Any] = {}
    if provider in ("strava", "fitbit", "whoop"):
        tokens["access_token"] = getattr(handler, "access_token", None)
        tokens["refresh_token"] = getattr(handler, "refresh_token", None)
        tokens["expires_at"] = getattr(handler, "expires_at", None)
    elif provider == "withings":
        tokens["access_token"] = getattr(handler, "access_token", None)
        tokens["refresh_token"] = getattr(handler, "refresh_token", None)
    elif provider == "garmin" and token_dir is not None:
        for name in ("garmin_tokens", "oauth1_token", "oauth2_token"):
            token_path = Path(token_dir) / f"{name}.json"
            if token_path.exists():
                try:
                    with open(token_path, "r", encoding="utf-8") as f:
                        tokens[name] = json.load(f)
                except Exception as e:
                    logger.warning(f"Could not read Garmin {name}: {e}")
    return {k: v for k, v in tokens.items() if v}


def has_tokens(provider: str, payload: Dict[str, Any]) -> bool:
    """True when the stored payload holds enough material to call the provider API."""
    if provider == "garmin":
        return bool(payload.get("garmin_tokens")) or bool(payload.get("oauth2_token")) or bool(payload.get("email") and payload.get("password"))
    if provider == "withings":
        return bool(payload.get("access_token") or payload.get("refresh_token"))
    return bool(payload.get("access_token"))


# --- SYNC DISPATCH ----------------------------------------------------------

def sync_provider(
    provider: str,
    db,
    payload: Dict[str, Any],
    days: Optional[int] = None,
    force_full: bool = False,
    timeout: float = 900.0,
    on_progress: Optional[Callable[[str], None]] = None,
) -> Dict[str, Any]:
    """
    Run a data sync for one provider and block until it completes (or times out).

    Returns {"success", "count", "message", "tokens"}. `tokens` holds refreshed
    OAuth material that the caller must persist back into the encrypted row.
    """
    if not is_valid_provider(provider):
        raise ValueError(f"Okänd datakälla: {provider}")

    meta = PROVIDERS[provider]
    sync_days = int(days or meta["sync_days"])

    def _progress(text: str):
        if on_progress:
            try:
                on_progress(text)
            except Exception:
                pass

    with temp_token_dir() as token_dir:
        handler: Any = build_handler(provider, db, payload, token_dir)

        if provider == "withings":
            _progress("Hämtar mätvärden från Withings...")
            result = handler.sync_withings_data(days=sync_days, force_full=force_full)
            tokens = collect_tokens(provider, handler)
            count = int(result.get("count") or 0)
            success = bool(result.get("success")) and count > 0
            if success:
                message = f"{count} vikt- och kroppssammansättningsmätningar sparade."
            else:
                message = result.get("message") or handler.last_error or "Inga mätvärden hämtades."
            return {"success": success, "count": count, "message": message, "tokens": tokens}

        if provider == "garmin":
            _progress("Loggar in på Garmin Connect...")
            with GARMIN_AUTH_LOCK:
                auth_res = handler.authenticate()
            if not auth_res.get("success"):
                if auth_res.get("mfa_required"):
                    message = "Garmin kräver en ny MFA-verifiering. Anslut kontot igen under Datakällor."
                else:
                    message = auth_res.get("error") or "Kunde inte logga in på Garmin Connect."
                return {"success": False, "count": 0, "message": message, "tokens": {}}

        done = threading.Event()
        outcome: Dict[str, Any] = {"count": 0, "error": None}

        def on_complete(*args):
            if args:
                try:
                    outcome["count"] = int(args[0] or 0)
                except (TypeError, ValueError):
                    outcome["count"] = 0
                if len(args) > 1 and args[1]:
                    outcome["error"] = str(args[1])
            done.set()

        def progress_adapter(_current, _total, text):
            _progress(text)

        _progress(f"Startar synkronisering med {meta['name']}...")

        if provider == "strava":
            handler.sync_strava_history(
                days=sync_days, force_full=force_full,
                on_progress=progress_adapter, on_complete=on_complete,
            )
        elif provider == "fitbit":
            handler.sync_fitbit_history(
                days=sync_days, force_full=force_full,
                on_progress=progress_adapter, on_complete=on_complete,
            )
        elif provider == "whoop":
            handler.sync_whoop_history(
                days=sync_days, force_full=force_full,
                on_progress=progress_adapter, on_complete=on_complete,
            )
        else:  # garmin
            handler.sync_garmin_history(
                days=sync_days, force_full=force_full,
                on_progress=progress_adapter, on_complete=on_complete,
            )

        finished = done.wait(timeout)
        tokens = collect_tokens(provider, handler, token_dir)

        if not finished:
            return {
                "success": False,
                "count": 0,
                "message": f"Synkroniseringen mot {meta['name']} tog för lång tid och avbröts.",
                "tokens": tokens,
            }
        if outcome["error"]:
            return {"success": False, "count": 0, "message": outcome["error"], "tokens": tokens}

        count = outcome["count"]
        last_error = getattr(handler, "last_error", None)
        if count:
            message = f"{count} {meta['sync_label']} synkroniserade."
        elif last_error:
            message = str(last_error)
        else:
            message = f"Synkronisering mot {meta['name']} klar."
        return {"success": True, "count": count, "message": message, "tokens": tokens}
