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


def test_sliding_window_caps_history_at_20_messages(monkeypatch):
    client = AIClient(provider="xai", api_key="test-key")
    # Mock the internal call so no network occurs
    monkeypatch.setattr(client, "_call_openai_compatible", lambda prompt, current: "mock response")
    
    for i in range(15):
        client.chat(f"Question {i}", garmin_context="HUGE CONTEXT STRING " * 100)

    # Total messages added = 15 users + 15 assistants = 30, but should cap at 20
    assert len(client.conversation_history) == 20
    # Verify that garmin_context is NOT stored in user message in history
    assert client.conversation_history[0]["content"] == "Question 5"


# --- Preload Ollama Model -----------------------------------------------------

def test_preload_ollama_model_already_resident(monkeypatch):
    from ai_client import preload_ollama_model

    called_urls = []
    class DummyResponse:
        def __init__(self, status_code, json_data):
            self.status_code = status_code
            self._json = json_data
            self.text = ""
        def json(self):
            return self._json

    def mock_get(url, timeout=3):
        called_urls.append(("GET", url))
        return DummyResponse(200, {"models": [{"name": "gemma4:12b:latest"}]})

    def mock_post(url, json=None, timeout=30):
        called_urls.append(("POST", url, json))
        return DummyResponse(200, {"response": ""})

    monkeypatch.setattr("requests.get", mock_get)
    monkeypatch.setattr("requests.post", mock_post)

    result = preload_ollama_model(base_url="http://192.168.107.15:11436", model="gemma4:12b")
    assert result is True
    # Verify GET /api/ps was called, but POST /api/generate was NOT called because model was already resident
    assert any(c[0] == "GET" and "/api/ps" in c[1] for c in called_urls)
    assert not any(c[0] == "POST" for c in called_urls)


def test_preload_ollama_model_not_resident_triggers_generate(monkeypatch):
    from ai_client import preload_ollama_model

    called_urls = []
    class DummyResponse:
        def __init__(self, status_code, json_data):
            self.status_code = status_code
            self._json = json_data
            self.text = ""
        def json(self):
            return self._json

    def mock_get(url, timeout=3):
        called_urls.append(("GET", url))
        return DummyResponse(200, {"models": [{"name": "llama3:latest"}]})

    def mock_post(url, json=None, timeout=30):
        called_urls.append(("POST", url, json))
        return DummyResponse(200, {"response": ""})

    monkeypatch.setattr("requests.get", mock_get)
    monkeypatch.setattr("requests.post", mock_post)

    result = preload_ollama_model(base_url="http://192.168.107.15:11436", model="gemma4:12b", keep_alive="45m")
    assert result is True
    # Verify both GET /api/ps and POST /api/generate were called
    assert any(c[0] == "GET" and "/api/ps" in c[1] for c in called_urls)
    post_calls = [c for c in called_urls if c[0] == "POST"]
    assert len(post_calls) == 1
    assert "/api/generate" in post_calls[0][1]
    assert post_calls[0][2] == {"model": "gemma4:12b", "keep_alive": "45m"}


def test_preload_ollama_model_unreachable_returns_false(monkeypatch):
    from ai_client import preload_ollama_model

    def mock_get(url, timeout=3):
        raise ConnectionError("Connection refused")

    monkeypatch.setattr("requests.get", mock_get)
    result = preload_ollama_model(base_url="http://non-existent-host:11434", model="gemma4:12b")
    assert result is False

