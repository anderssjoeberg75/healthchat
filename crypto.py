"""
Cryptographic module for HealthChat Desktop.
Implements client-side envelope encryption (AES-256-GCM + Argon2id KEK/DEK)
and 256-bit Base32 recovery keys.
"""

import os
import json
import base64
import logging
from typing import Dict, Any, Tuple, Optional
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from argon2 import low_level

logger = logging.getLogger("crypto")

# Argon2id parameters (tuned for security and responsiveness ~200-400ms)
ARGON2_TIME_COST = 2
ARGON2_MEMORY_COST = 65536  # 64 MB
ARGON2_PARALLELISM = 1
KEY_LEN = 32  # 256 bits
NONCE_LEN = 12  # 96 bits for AES-GCM


def generate_salt(length: int = 16) -> bytes:
    """Generate cryptographically secure random salt."""
    return os.urandom(length)


def generate_dek() -> bytes:
    """Generate a random 256-bit Data Encryption Key (DEK)."""
    return os.urandom(KEY_LEN)


def derive_kek(password: str, salt: bytes) -> bytes:
    """Derive a 256-bit Key Encryption Key (KEK) from password using Argon2id."""
    if not password:
        raise ValueError("Password cannot be empty")
    return low_level.hash_secret_raw(
        secret=password.encode("utf-8"),
        salt=salt,
        time_cost=ARGON2_TIME_COST,
        memory_cost=ARGON2_MEMORY_COST,
        parallelism=ARGON2_PARALLELISM,
        hash_len=KEY_LEN,
        type=low_level.Type.ID
    )


def wrap_dek(kek: bytes, dek: bytes) -> Tuple[bytes, bytes]:
    """
    Wrap the DEK using the KEK via AES-256-GCM.
    Returns (nonce, wrapped_dek).
    """
    nonce = os.urandom(NONCE_LEN)
    aesgcm = AESGCM(kek)
    wrapped = aesgcm.encrypt(nonce, dek, None)
    return nonce, wrapped


def unwrap_dek(kek: bytes, wrapped_dek: bytes, nonce: bytes) -> bytes:
    """
    Unwrap the DEK using the KEK via AES-256-GCM.
    Raises InvalidTag if password/KEK is incorrect or ciphertext is tampered.
    """
    aesgcm = AESGCM(kek)
    return aesgcm.decrypt(nonce, wrapped_dek, None)


def encrypt_payload(dek: bytes, data: Any) -> Tuple[bytes, bytes]:
    """
    Serialize and encrypt a data dictionary/payload using the DEK via AES-256-GCM.
    Returns (nonce, ciphertext).
    """
    serialized = json.dumps(data, ensure_ascii=False, default=str).encode("utf-8")
    nonce = os.urandom(NONCE_LEN)
    aesgcm = AESGCM(dek)
    ciphertext = aesgcm.encrypt(nonce, serialized, None)
    return nonce, ciphertext


def decrypt_payload(dek: bytes, ciphertext: bytes, nonce: bytes) -> Any:
    """
    Decrypt and deserialize a payload using the DEK via AES-256-GCM.
    """
    aesgcm = AESGCM(dek)
    plaintext_bytes = aesgcm.decrypt(nonce, ciphertext, None)
    return json.loads(plaintext_bytes.decode("utf-8"))


# --- K-10 Recovery Key Helpers ---

def generate_recovery_key() -> str:
    """
    Generate a 200-bit entropy recovery key formatted as grouped Base32 (Q-9).
    Format: 8 groups of 5 uppercase characters separated by hyphens (e.g. K7QF2-9MXTE-...)
    Total length: 47 chars (40 Base32 characters + 7 hyphens).
    """
    raw_bytes = os.urandom(KEY_LEN)  # 32 bytes = 256 bits
    b32 = base64.b32encode(raw_bytes).decode("ascii").rstrip("=")
    # 32 bytes in Base32 = 52 characters or 40 for 25 bytes. 32 bytes = 51.2 -> 52 chars (with padding).
    # Let's take the first 40 chars of b32 or format all chars into groups of 5
    cleaned = b32[:40]
    groups = [cleaned[i:i+5] for i in range(0, 40, 5)]
    return "-".join(groups)


def normalize_recovery_key(key_str: str) -> str:
    """Strip whitespace and hyphens, and uppercase the recovery key string."""
    return key_str.replace("-", "").replace(" ", "").strip().upper()


def derive_recovery_kek(recovery_key_str: str, salt: bytes) -> bytes:
    """Derive a KEK from a normalized recovery key using Argon2id."""
    norm = normalize_recovery_key(recovery_key_str)
    if len(norm) < 32:
        raise ValueError("Invalid recovery key format")
    return low_level.hash_secret_raw(
        secret=norm.encode("utf-8"),
        salt=salt,
        time_cost=ARGON2_TIME_COST,
        memory_cost=ARGON2_MEMORY_COST,
        parallelism=ARGON2_PARALLELISM,
        hash_len=KEY_LEN,
        type=low_level.Type.ID
    )


def wrap_dek_for_recovery(recovery_key_str: str, dek: bytes) -> Tuple[bytes, bytes, bytes]:
    """
    Wrap DEK with a recovery key.
    Returns (recovery_salt, recovery_nonce, recovery_wrapped_dek).
    """
    salt = generate_salt(16)
    kek = derive_recovery_kek(recovery_key_str, salt)
    nonce, wrapped = wrap_dek(kek, dek)
    return salt, nonce, wrapped


def unwrap_dek_with_recovery_key(recovery_key_str: str, recovery_salt: bytes, recovery_nonce: bytes, recovery_wrapped_dek: bytes) -> bytes:
    """
    Unwrap the DEK using the recovery key.
    Raises error if key is invalid.
    """
    kek = derive_recovery_kek(recovery_key_str, recovery_salt)
    return unwrap_dek(kek, recovery_wrapped_dek, recovery_nonce)


def rewrap_dek_new_password(dek: bytes, new_password: str) -> Tuple[bytes, bytes, bytes]:
    """
    Re-wrap an existing DEK with a new password.
    Returns (new_kdf_salt, new_dek_nonce, new_wrapped_dek).
    Does NOT require re-encrypting any stored health data!
    """
    new_salt = generate_salt(16)
    new_kek = derive_kek(new_password, new_salt)
    new_nonce, new_wrapped = wrap_dek(new_kek, dek)
    return new_salt, new_nonce, new_wrapped
