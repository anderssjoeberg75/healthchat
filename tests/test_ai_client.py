"""Tests for ai_client.AIClient.

Only the offline-safe surface is exercised: URL normalization, provider
metadata, model selection and validation, and conversation reset. No test
here performs a network request or a real model call.
"""

import pytest

from ai_client import AIClient


# --- normalize_ollama_url ------------------------------------------------------

@pytest.mark.parametrize("raw, expected", [
    ("", "http://localhost:11434/v1"),
    ("   ", "http://localhost:11434/v1"),
    ("192.168.107.15", "http://192.168.107.15:11434/v1"),
    ("http:/192.168.107.15:11434", "http://192.168.107.15:11434/v1"),
    ("http://192.168.107.15", "http://192.168.107.15:11434/v1"),
    ("localhost:11434/v1", "http://localhost:11434/v1"),
    ("https://example.com:8080", "https://example.com:8080/v1"),
    ("http://localhost:11434/v1", "http://localhost:11434/v1"),
])
def test_normalize_ollama_url(raw, expected):
    assert AIClient.normalize_ollama_url(raw) == expected


def test_normalize_ollama_url_defaults_port_and_scheme():
    # Bare hostname gets the default Ollama port and http scheme.
    assert AIClient.normalize_ollama_url("myhost") == "http://myhost:11434/v1"


# --- Provider metadata ---------------------------------------------------------

def test_get_available_providers_contains_all_six():
    providers = AIClient.get_available_providers()
    assert set(providers) == {
        "xai", "openai", "azure", "gemini", "anthropic", "ollama",
    }


def test_every_provider_has_required_keys():
    for name, cfg in AIClient.get_available_providers().items():
        assert "name" in cfg, name
        assert "models" in cfg, name
        assert "default_model" in cfg, name


def test_get_provider_models_known():
    models = AIClient.get_provider_models("xai")
    assert "grok-3" in models


def test_get_provider_models_unknown_returns_empty():
    assert AIClient.get_provider_models("does-not-exist") == []


# --- Construction / model selection --------------------------------------------

def test_unknown_provider_raises():
    with pytest.raises(ValueError):
        AIClient(provider="not-a-provider", api_key="x")


def test_default_model_selected_when_none_given():
    client = AIClient(provider="xai", api_key="test-key")
    assert client.model == "grok-3"


def test_explicit_model_overrides_default():
    client = AIClient(provider="openai", api_key="test-key", model="gpt-4o-mini")
    assert client.model == "gpt-4o-mini"


def test_azure_requires_endpoint():
    with pytest.raises(ValueError):
        AIClient(provider="azure", api_key="test-key")


def test_ollama_constructs_without_api_key():
    # Ollama needs no real key; construction must not hit the network.
    client = AIClient(provider="ollama", api_key="", model="llama3.2")
    assert client.provider == "ollama"
    assert client.model == "llama3.2"


def test_new_client_starts_with_empty_history():
    client = AIClient(provider="xai", api_key="test-key")
    assert client.conversation_history == []


def test_reset_conversation_clears_history():
    client = AIClient(provider="xai", api_key="test-key")
    client.conversation_history.append({"role": "user", "content": "hi"})
    client.reset_conversation()
    assert client.conversation_history == []
