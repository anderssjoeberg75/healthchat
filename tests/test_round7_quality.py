"""
Unit tests for Omgång 7 quality, dependencies, test isolation, and security improvements:
- TLS-4: Ollama HTTPS support and non-loopback warning
- Q-3 & Q-4: Azure model validation and deployment parameter
- Q-5: AI response whitespace preservation for code blocks
- Q-6: AI conversation history rollback on failure
- Q-7: Ollama base URL in connection failure messages
- Q-8: Register user duplicate email handling (ValueError / 400)
- Q-9: Recovery key entropy docstring/length, delete_account password verification, get_db_conn None safety
- Q-1: Profile refresh endpoint and profile_sync
"""

import sqlite3
import pytest
import logging
from ai_client import normalize_ollama_url, AIClient
import crypto
import auth
import profile_sync


def test_tls4_normalize_ollama_url_https_and_warnings(caplog):
    """TLS-4: HTTPS should default to port 443; non-loopback http should log a warning."""
    # 1. HTTPS URL
    url = normalize_ollama_url("https://ollama.example.se")
    assert url == "https://ollama.example.se:443/v1"

    url_port = normalize_ollama_url("https://ollama.example.se:8443")
    assert url_port == "https://ollama.example.se:8443/v1"

    # 2. Local loopback should NOT log a security warning
    caplog.clear()
    with caplog.at_level(logging.WARNING):
        local_url = normalize_ollama_url("http://127.0.0.1:11434")
        assert local_url == "http://127.0.0.1:11434/v1"
        assert not any("okrypterad" in rec.message for rec in caplog.records)

    # 3. Non-loopback HTTP should log a warning about unencrypted traffic
    caplog.clear()
    with caplog.at_level(logging.WARNING):
        remote_url = normalize_ollama_url("http://192.168.1.100:11434")
        assert remote_url == "http://192.168.1.100:11434/v1"
        assert any("okrypterad" in rec.message for rec in caplog.records)


def test_q3_azure_missing_model_raises_value_error():
    """Q-3: Azure client without model or deployment must raise clear ValueError."""
    with pytest.raises(ValueError) as excinfo:
        AIClient(provider="azure", azure_endpoint="https://example.openai.azure.com/")
    assert "Azure OpenAI kräver att antingen" in str(excinfo.value)


def test_q4_azure_deployment_used_as_model(monkeypatch):
    """Q-4: Explicit azure_deployment should be passed as model to API."""
    client = AIClient(
        provider="azure",
        api_key="test-key",
        azure_endpoint="https://myazure.openai.azure.com/",
        azure_deployment="my-custom-deployment",
        model="some-underlying-model"
    )
    assert client.azure_deployment == "my-custom-deployment"
    assert client.model == "my-custom-deployment"


def test_q5_code_block_indentation_preserved():
    """Q-5: Response cleaning must preserve indentation in code blocks."""
    client = AIClient(provider="openai", api_key="test-key")
    markdown_with_code = (
        "Här är ett Python-skript:\n\n"
        "```python\n"
        "def hello():\n"
        "    message = 'Hello world'\n"
        "    if True:\n"
        "        print(message)\n"
        "```\n\n"
        "Lycka till!"
    )
    cleaned = client._clean_response(markdown_with_code)
    assert "    message = 'Hello world'" in cleaned
    assert "        print(message)" in cleaned


def test_q6_ai_history_rolled_back_on_error(monkeypatch):
    """Q-6: If chat API call fails, user message must be rolled back to keep alternating roles."""
    client = AIClient(provider="openai", api_key="dummy-key")
    assert len(client.conversation_history) == 0

    def mock_call_error(*args, **kwargs):
        raise ConnectionError("Network unreachable")

    monkeypatch.setattr(client, "_call_openai_compatible", mock_call_error)

    reply = client.chat("Hej, hur mår jag?")
    assert "Error" in reply or "Fel" in reply or "Kunde inte ansluta" in reply
    # History should be empty because the user message was rolled back
    assert len(client.conversation_history) == 0


def test_q7_ollama_error_message_contains_configured_url(monkeypatch):
    """Q-7: Ollama connection error message should display the actual configured base_url."""
    custom_host = "http://192.168.10.25:11434"
    client = AIClient(provider="ollama", ollama_base_url=custom_host)

    def mock_call_error(*args, **kwargs):
        raise ConnectionError("Failed to connect: connection refused")

    monkeypatch.setattr(client, "_call_openai_compatible", mock_call_error)

    reply = client.chat("Hej Ollama")
    assert "192.168.10.25:11434" in reply


def test_q8_register_user_duplicate_email_raises_value_error():
    """Q-8: Registering with an existing email raises ValueError('E-postadressen är redan registrerad.')."""
    conn = sqlite3.connect(":memory:")
    conn.execute("""
        CREATE TABLE users (
            id INTEGER PRIMARY KEY,
            email TEXT UNIQUE,
            password_hash TEXT,
            kdf_salt BLOB,
            wrapped_dek BLOB,
            dek_nonce BLOB,
            recovery_key_hash TEXT,
            recovery_wrapped_dek BLOB,
            recovery_salt BLOB,
            recovery_nonce BLOB,
            encrypted_profile BLOB,
            profile_nonce BLOB,
            created_at TIMESTAMP
        )
    """)
    conn.commit()

    # Register first user
    auth.register_user(conn, "duplicate@example.com", "Password123!")

    # Attempt second registration with same email
    with pytest.raises(ValueError) as excinfo:
        auth.register_user(conn, "duplicate@example.com", "DifferentPassword123!")
    assert "redan registrerad" in str(excinfo.value)


def test_q9_recovery_key_length_and_format():
    """Q-9 p1: Recovery key is 40 Base32 characters formatted in 8 groups of 5."""
    key = crypto.generate_recovery_key()
    parts = key.split("-")
    assert len(parts) == 8
    for p in parts:
        assert len(p) == 5
    clean = key.replace("-", "")
    assert len(clean) == 40  # 40 * 5 bits = 200 bits of entropy


def test_q9_delete_user_account_password_verification():
    """Q-9 p5: delete_user_account verifies current_password if provided."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("CREATE TABLE users (id INTEGER PRIMARY KEY, email TEXT, password_hash TEXT)")
    conn.execute("CREATE TABLE user_sessions (session_id TEXT, user_id INTEGER)")

    pw_hash = auth.hash_password("Secret123!")
    conn.execute("INSERT INTO users (id, email, password_hash) VALUES (1, 'user@example.com', ?)", (pw_hash,))
    conn.commit()

    # 1. Incorrect password raises ValueError
    with pytest.raises(ValueError) as excinfo:
        auth.delete_user_account(conn, 1, current_password="WrongPassword")
    assert "Felaktigt lösenord" in str(excinfo.value)

    # 2. Correct password deletes account
    auth.delete_user_account(conn, 1, current_password="Secret123!")
    cur = conn.execute("SELECT COUNT(*) FROM users WHERE id = 1")
    assert cur.fetchone()[0] == 0


def test_q1_profile_sync_refresh_alias():
    """Q-1: Verify refresh_profile_metrics works as alias for fetch_external_profile_metrics."""
    class MockDB:
        def get_latest_body_composition(self):
            return {"weight_kg": 75.0, "bmi": 23.1}
        def get_daily_summary_history(self, days=30):
            return [{"resting_hr": 52}]

    res = profile_sync.refresh_profile_metrics(db=MockDB())
    assert res["metrics"]["weight_kg"] == 75.0
    assert res["metrics"]["resting_hr"] == 52
    assert "Databas" in res["sources"]

    # Alias produces identical output
    res2 = profile_sync.fetch_external_profile_metrics(db=MockDB())
    assert res2 == res


def test_q9_get_db_conn_returns_none_on_failure():
    """Q-9 p3: server.get_db_conn returns None instead of raising unhandled exception when DB fails."""
    import server

    class BrokenDB:
        is_mariadb = True
        pool = True
        def get_mariadb_conn(self):
            raise ConnectionError("MariaDB pool exhausted")

    conn = server.get_db_conn(BrokenDB())
    assert conn is None
