"""
Secrets Management for HealthChat Desktop & Web Application.
Stores sensitive API keys and OAuth tokens securely in OS Keyring / Credential Manager.
Provides transparent migration out of plaintext config files.
"""

import os
import logging

try:
    import keyring
except ImportError:
    keyring = None
from typing import Optional, Dict, Any

logger = logging.getLogger("secret_store")

SERVICE_NAME = "HealthChatDesktop_Secrets"

SECRET_KEYS = (
    "xai_api_key",
    "openai_api_key",
    "azure_api_key",
    "gemini_api_key",
    "anthropic_api_key",
    "garmin_password",
    "garmin_email",
    "withings_client_secret",
    "withings_refresh_token",
    "withings_access_token",
    "strava_client_secret",
    "strava_refresh_token",
    "strava_access_token",
    "fitbit_client_secret",
    "fitbit_refresh_token",
    "fitbit_access_token",
)


def get_secret(name: str) -> Optional[str]:
    """Retrieve secret string from Keyring, falling back to environment variables."""
    if keyring is not None:
        try:
            val = keyring.get_password(SERVICE_NAME, name)
            if val and str(val).strip():
                return str(val).strip()
        except Exception as e:
            logger.debug(f"Keyring lookup failed for '{name}': {e}")
    
    env_val = os.environ.get(name.upper()) or os.environ.get(name)
    if env_val and str(env_val).strip():
        return str(env_val).strip()

    return None


def set_secret(name: str, value: Optional[str]) -> bool:
    """Set or delete secret string in Keyring."""
    if keyring is None:
        return False
    try:
        if value:
            keyring.set_password(SERVICE_NAME, name, str(value))
        else:
            try:
                keyring.delete_password(SERVICE_NAME, name)
            except Exception:
                pass
        return True
    except Exception as e:
        logger.warning(f"Failed setting secret '{name}' in keyring: {e}")
        return False


def delete_secret(name: str) -> bool:
    """Delete secret string from Keyring."""
    return set_secret(name, None)


def migrate_config_secrets(config: Dict[str, Any]) -> tuple[Dict[str, Any], bool]:
    """
    Migrate plaintext secrets from config dict into OS Keyring.
    Returns (cleaned_config, migrated_any).
    """
    cleaned = dict(config)
    migrated = False

    for key in SECRET_KEYS:
        if key in cleaned:
            val = cleaned.pop(key, None)
            if val and str(val).strip():
                set_secret(key, str(val).strip())
                migrated = True

    return cleaned, migrated
