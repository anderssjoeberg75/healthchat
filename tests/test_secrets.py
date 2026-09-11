"""
Unit tests for secret_store.py keyring storage and config secret migration.
"""

from unittest.mock import patch
import secret_store


def test_set_get_delete_secret():
    storage = {}

    def mock_get(service, name):
        return storage.get(name)

    def mock_set(service, name, val):
        storage[name] = val

    def mock_delete(service, name):
        storage.pop(name, None)

    with patch("keyring.get_password", side_effect=mock_get), \
         patch("keyring.set_password", side_effect=mock_set), \
         patch("keyring.delete_password", side_effect=mock_delete):
        
        assert secret_store.get_secret("openai_api_key") is None

        assert secret_store.set_secret("openai_api_key", "sk-test123456") is True
        assert secret_store.get_secret("openai_api_key") == "sk-test123456"

        assert secret_store.delete_secret("openai_api_key") is True
        assert secret_store.get_secret("openai_api_key") is None


def test_migrate_config_secrets():
    storage = {}

    def mock_set(service, name, val):
        storage[name] = val

    raw_config = {
        "ai_provider": "OpenAI",
        "openai_api_key": "sk-secret-key-123",
        "withings_client_secret": "w-secret-456",
        "dark_mode": True,
    }

    with patch("keyring.set_password", side_effect=mock_set):
        cleaned, migrated = secret_store.migrate_config_secrets(raw_config)

    assert migrated is True
    assert "openai_api_key" not in cleaned
    assert "withings_client_secret" not in cleaned
    assert cleaned["ai_provider"] == "OpenAI"
    assert cleaned["dark_mode"] is True

    assert storage["openai_api_key"] == "sk-secret-key-123"
    assert storage["withings_client_secret"] == "w-secret-456"
