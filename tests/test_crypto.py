"""
Tests for crypto.py envelope encryption and recovery keys.
"""

import pytest
from cryptography.exceptions import InvalidTag
import crypto

def test_wrap_unwrap_dek():
    password = "TestPassword123!"
    salt = crypto.generate_salt(16)
    kek = crypto.derive_kek(password, salt)
    dek = crypto.generate_dek()

    nonce, wrapped = crypto.wrap_dek(kek, dek)
    assert len(nonce) == 12
    assert wrapped != dek

    unwrapped = crypto.unwrap_dek(kek, wrapped, nonce)
    assert unwrapped == dek

def test_unwrap_dek_with_wrong_password_fails():
    salt = crypto.generate_salt(16)
    kek1 = crypto.derive_kek("Password123!", salt)
    kek2 = crypto.derive_kek("WrongPassword!", salt)
    dek = crypto.generate_dek()

    nonce, wrapped = crypto.wrap_dek(kek1, dek)

    with pytest.raises(InvalidTag):
        crypto.unwrap_dek(kek2, wrapped, nonce)

def test_payload_encryption_and_decryption():
    dek = crypto.generate_dek()
    original_data = {
        "steps": 12500,
        "calories": 2450,
        "avg_hr": 68,
        "notes": "Löpning i skogen med Withings/Garmin",
        "nested": {"key": [1, 2, 3]}
    }

    nonce, ciphertext = crypto.encrypt_payload(dek, original_data)
    assert ciphertext != original_data

    decrypted = crypto.decrypt_payload(dek, ciphertext, nonce)
    assert decrypted == original_data

def test_tampered_payload_fails():
    dek = crypto.generate_dek()
    data = {"value": 42}
    nonce, ciphertext = crypto.encrypt_payload(dek, data)

    # Tamper with 1 byte of ciphertext
    tampered = bytearray(ciphertext)
    tampered[0] ^= 0x01

    with pytest.raises(InvalidTag):
        crypto.decrypt_payload(dek, bytes(tampered), nonce)

def test_recovery_key_generation_and_unwrap():
    dek = crypto.generate_dek()
    rec_key = crypto.generate_recovery_key()
    assert len(rec_key.replace("-", "")) == 40
    assert "-" in rec_key

    salt, nonce, wrapped = crypto.wrap_dek_for_recovery(rec_key, dek)
    unwrapped = crypto.unwrap_dek_with_recovery_key(rec_key, salt, nonce, wrapped)
    assert unwrapped == dek

    # Test with lowercase and without hyphens
    unwrapped_dirty = crypto.unwrap_dek_with_recovery_key(rec_key.lower().replace("-", " "), salt, nonce, wrapped)
    assert unwrapped_dirty == dek

def test_invalid_recovery_key_fails():
    dek = crypto.generate_dek()
    rec_key1 = crypto.generate_recovery_key()
    rec_key2 = crypto.generate_recovery_key()

    salt, nonce, wrapped = crypto.wrap_dek_for_recovery(rec_key1, dek)

    with pytest.raises(InvalidTag):
        crypto.unwrap_dek_with_recovery_key(rec_key2, salt, nonce, wrapped)

def test_rewrap_dek_new_password_preserves_data():
    old_pw = "OldPassword123"
    new_pw = "NewPassword456"

    salt = crypto.generate_salt(16)
    kek = crypto.derive_kek(old_pw, salt)
    dek = crypto.generate_dek()
    nonce, wrapped = crypto.wrap_dek(kek, dek)

    # Encrypt some health data with the DEK
    health_payload = {"resting_hr": 55, "weight_kg": 78.4}
    p_nonce, ciphertext = crypto.encrypt_payload(dek, health_payload)

    # Now change password (re-wrap DEK)
    unwrapped_dek = crypto.unwrap_dek(kek, wrapped, nonce)
    new_salt, new_nonce, new_wrapped = crypto.rewrap_dek_new_password(unwrapped_dek, new_pw)

    # Later, login with new password
    login_kek = crypto.derive_kek(new_pw, new_salt)
    login_dek = crypto.unwrap_dek(login_kek, new_wrapped, new_nonce)

    # Health data is still decrypted perfectly with login_dek!
    decrypted_health = crypto.decrypt_payload(login_dek, ciphertext, p_nonce)
    assert decrypted_health == health_payload
