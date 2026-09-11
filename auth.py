"""
Authentication and session management module for HealthChat Desktop.
Implements Argon2id hashing, user registration, authentication,
account recovery via Base32 keys, and secure OS keyring session storage.
"""

import time
import base64
import logging
from typing import Optional, Tuple, Dict, Any
from dataclasses import dataclass
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError, InvalidHashError, VerificationError

import crypto

logger = logging.getLogger("auth")


def mask_email(email: str) -> str:
    """Mask email for logging to avoid storing plain PII."""
    if not email or "@" not in email:
        return "***"
    parts = email.split("@", 1)
    name, domain = parts[0], parts[1]
    if len(name) <= 2:
        masked_name = name[0] + "*"
    else:
        masked_name = name[0] + "*" * (len(name) - 2) + name[-1]
    return f"{masked_name}@{domain}"


# Argon2id password hasher
ph = PasswordHasher(
    time_cost=2,
    memory_cost=65536,  # 64 MB
    parallelism=1,
    hash_len=32,
    type=crypto.low_level.Type.ID
)

# In-memory login attempt tracker for rate-limiting / progressive backoff
_failed_attempts: Dict[str, list] = {}


@dataclass
class UserSession:
    user_id: int
    email: str
    dek: bytearray
    encrypted_profile: Optional[Dict[str, Any]] = None

    def clear(self):
        """Zero out DEK bytes in memory on logout."""
        if self.dek:
            for i in range(len(self.dek)):
                self.dek[i] = 0


def hash_password(password: str) -> str:
    """Hash password using Argon2id."""
    return ph.hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    """Verify password against Argon2id hash."""
    try:
        return ph.verify(password_hash, password)
    except VerifyMismatchError:
        return False
    except (InvalidHashError, VerificationError) as e:
        logger.error(f"Argon2 hash verification failed due to corruption/invalid hash: {e}")
        return False
    except Exception as e:
        logger.error(f"Unexpected error during Argon2 password verification: {e}")
        return False


def password_needs_rehash(password_hash: str) -> bool:
    """Check if Argon2id password hash needs rehash under current parameters."""
    try:
        return ph.check_needs_rehash(password_hash)
    except Exception:
        return True



def validate_email(email: str) -> bool:
    """Basic email format validation."""
    if not email or "@" not in email or "." not in email:
        return False
    parts = email.strip().split("@")
    if len(parts) != 2 or not parts[0] or not parts[1]:
        return False
    return True


def check_rate_limit(email: str) -> bool:
    """Check if login attempts are being rate-limited (max 5 failed attempts per minute)."""
    clean_email = email.lower().strip()
    now = time.time()
    if clean_email in _failed_attempts:
        # Keep only attempts within last 60 seconds
        _failed_attempts[clean_email] = [t for t in _failed_attempts[clean_email] if now - t < 60]
        if len(_failed_attempts[clean_email]) >= 5:
            return False
    return True


def record_failed_attempt(email: str):
    """Record a failed login attempt for rate limiting."""
    clean_email = email.lower().strip()
    now = time.time()
    if clean_email not in _failed_attempts:
        _failed_attempts[clean_email] = []
    _failed_attempts[clean_email].append(now)


def clear_failed_attempts(email: str):
    """Clear failed login attempts upon successful login."""
    clean_email = email.lower().strip()
    _failed_attempts.pop(clean_email, None)


def register_user(
    db_conn,
    email: str,
    password: str,
    initial_profile: Optional[Dict[str, Any]] = None
) -> Tuple[int, str, UserSession]:
    """
    Register a new user in the MariaDB database.
    Returns (user_id, recovery_key, UserSession).
    """
    clean_email = email.lower().strip()
    if not validate_email(clean_email):
        raise ValueError("Ogiltig e-postadress.")
    if len(password) < 8:
        raise ValueError("Lösenordet måste vara minst 8 tecken långt.")

    # Generate DEK and wrap with user password KEK
    salt = crypto.generate_salt(16)
    kek = crypto.derive_kek(password, salt)
    dek = crypto.generate_dek()
    dek_nonce, wrapped_dek = crypto.wrap_dek(kek, dek)

    # Generate 256-bit recovery key and wrap DEK for recovery
    recovery_key = crypto.generate_recovery_key()
    rec_salt, rec_nonce, rec_wrapped = crypto.wrap_dek_for_recovery(recovery_key, dek)

    # Hash password with Argon2id
    pwd_hash = hash_password(password)

    # Encrypt initial profile if provided
    enc_profile = None
    profile_nonce = None
    if initial_profile:
        profile_nonce, enc_profile = crypto.encrypt_payload(dek, initial_profile)

    with db_conn.cursor() as cur:
        sql = """
        INSERT INTO users (
            email, password_hash, kdf_salt, wrapped_dek, dek_nonce,
            recovery_wrapped_dek, recovery_salt, recovery_nonce,
            encrypted_profile, profile_nonce
        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """
        cur.execute(sql, (
            clean_email, pwd_hash, salt, wrapped_dek, dek_nonce,
            rec_wrapped, rec_salt, rec_nonce,
            enc_profile, profile_nonce
        ))
        user_id = cur.lastrowid
        db_conn.commit()

    logger.info(f"Successfully registered user {mask_email(clean_email)} (id: {user_id})")
    session = UserSession(user_id=user_id, email=clean_email, dek=bytearray(dek), encrypted_profile=initial_profile or {})
    return user_id, recovery_key, session


def authenticate_user(db_conn, email: str, password: str) -> UserSession:
    """
    Authenticate a user with email and password.
    Returns UserSession with unwrapped DEK on success.
    Raises ValueError with generic error message on failure.
    """
    clean_email = email.lower().strip()
    if not clean_email or not password:
        raise ValueError("Fel e-postadress eller lösenord.")

    if not check_rate_limit(clean_email):
        time.sleep(1.0)
        raise ValueError("För många misslyckade inloggningsförsök. Vänta en minut och försök igen.")

    with db_conn.cursor() as cur:
        cur.execute(
            """
            SELECT id, email, password_hash, kdf_salt, wrapped_dek, dek_nonce,
                   encrypted_profile, profile_nonce
            FROM users WHERE email = %s
            """,
            (clean_email,)
        )
        row = cur.fetchone()

    if not row:
        record_failed_attempt(clean_email)
        time.sleep(0.3)
        raise ValueError("Fel e-postadress eller lösenord.")

    user_id = row[0]
    db_email = row[1]
    pwd_hash = row[2]
    salt = row[3]
    wrapped_dek = row[4]
    dek_nonce = row[5]
    enc_profile = row[6]
    profile_nonce = row[7]

    # Verify password hash
    if not verify_password(pwd_hash, password):
        record_failed_attempt(clean_email)
        time.sleep(0.3)
        raise ValueError("Fel e-postadress eller lösenord.")

    # Re-hash password if Argon2 parameters were updated
    if password_needs_rehash(pwd_hash):
        try:
            new_pwd_hash = hash_password(password)
            with db_conn.cursor() as cur:
                cur.execute("UPDATE users SET password_hash = %s WHERE id = %s", (new_pwd_hash, user_id))
                db_conn.commit()
            logger.info(f"Re-hashed password for user id {user_id} with updated Argon2 parameters.")
        except Exception as rehash_err:
            logger.warning(f"Failed to update re-hashed password for user id {user_id}: {rehash_err}")

    # Derive KEK and unwrap DEK
    try:
        kek = crypto.derive_kek(password, salt)
        dek = crypto.unwrap_dek(kek, wrapped_dek, dek_nonce)
    except Exception as e:
        record_failed_attempt(clean_email)
        logger.error(f"Error unwrapping DEK for user id {user_id}: {e}")
        raise ValueError("Fel e-postadress eller lösenord.")

    clear_failed_attempts(clean_email)

    profile_data = {}
    if enc_profile and profile_nonce:
        try:
            profile_data = crypto.decrypt_payload(dek, enc_profile, profile_nonce)
        except Exception as pe:
            logger.warning(f"Could not decrypt profile data for user id {user_id}: {pe}")

    logger.info(f"User id {user_id} ({mask_email(clean_email)}) authenticated successfully.")
    return UserSession(user_id=user_id, email=db_email, dek=bytearray(dek), encrypted_profile=profile_data)


def recover_account(
    db_conn,
    email: str,
    recovery_key_str: str,
    new_password: str
) -> Tuple[str, UserSession]:
    """
    Recover an account using the recovery key and set a new password.
    Generates and returns a NEW recovery key (old recovery key is invalidated).
    """
    clean_email = email.lower().strip()
    if not clean_email or not recovery_key_str:
        raise ValueError("Felaktiga återställningsuppgifter.")
    if len(new_password) < 8:
        raise ValueError("Det nya lösenordet måste vara minst 8 tecken långt.")

    with db_conn.cursor() as cur:
        cur.execute(
            """
            SELECT id, email, recovery_wrapped_dek, recovery_salt, recovery_nonce,
                   encrypted_profile, profile_nonce
            FROM users WHERE email = %s
            """,
            (clean_email,)
        )
        row = cur.fetchone()

    if not row:
        time.sleep(0.5)
        raise ValueError("Felaktiga återställningsuppgifter.")

    user_id = row[0]
    db_email = row[1]
    rec_wrapped = row[2]
    rec_salt = row[3]
    rec_nonce = row[4]
    enc_profile = row[5]
    profile_nonce = row[6]

    # Unwrap DEK using recovery key
    try:
        dek = crypto.unwrap_dek_with_recovery_key(recovery_key_str, rec_salt, rec_nonce, rec_wrapped)
    except Exception as ex:
        logger.warning(f"Recovery key unwrapping failed for {mask_email(clean_email)}: {ex}")
        time.sleep(0.5)
        raise ValueError("Ogiltig återställningsnyckel.")

    # Re-wrap DEK with new password
    new_salt, new_dek_nonce, new_wrapped_dek = crypto.rewrap_dek_new_password(dek, new_password)
    new_pwd_hash = hash_password(new_password)

    # Generate NEW recovery key and re-wrap DEK for recovery
    new_recovery_key = crypto.generate_recovery_key()
    new_rec_salt, new_rec_nonce, new_rec_wrapped = crypto.wrap_dek_for_recovery(new_recovery_key, dek)

    with db_conn.cursor() as cur:
        sql = """
        UPDATE users SET
            password_hash = %s,
            kdf_salt = %s,
            wrapped_dek = %s,
            dek_nonce = %s,
            recovery_wrapped_dek = %s,
            recovery_salt = %s,
            recovery_nonce = %s
        WHERE id = %s
        """
        cur.execute(sql, (
            new_pwd_hash, new_salt, new_wrapped_dek, new_dek_nonce,
            new_rec_wrapped, new_rec_salt, new_rec_nonce,
            user_id
        ))
        db_conn.commit()

    profile_data = {}
    if enc_profile and profile_nonce:
        try:
            profile_data = crypto.decrypt_payload(dek, enc_profile, profile_nonce)
        except Exception:
            pass

    logger.info(f"Account recovered and password updated for user id {user_id}")
    session = UserSession(user_id=user_id, email=db_email, dek=bytearray(dek), encrypted_profile=profile_data)
    return new_recovery_key, session


def change_user_password(
    db_conn,
    user_id: int,
    current_password: str,
    new_password: str
) -> bool:
    """
    Change user password by re-wrapping DEK with the new password KEK.
    Does NOT require re-encrypting any stored health data!
    """
    if len(new_password) < 8:
        raise ValueError("Det nya lösenordet måste vara minst 8 tecken långt.")

    with db_conn.cursor() as cur:
        cur.execute("SELECT password_hash, kdf_salt, wrapped_dek, dek_nonce FROM users WHERE id = %s", (user_id,))
        row = cur.fetchone()

    if not row:
        raise ValueError("Användaren hittades inte.")

    pwd_hash = row[0]
    salt = row[1]
    wrapped_dek = row[2]
    dek_nonce = row[3]

    if not verify_password(pwd_hash, current_password):
        raise ValueError("Det nuvarande lösenordet är felaktigt.")

    # Unwrap DEK with current password
    kek = crypto.derive_kek(current_password, salt)
    dek = crypto.unwrap_dek(kek, wrapped_dek, dek_nonce)

    # Re-wrap with new password
    new_salt, new_nonce, new_wrapped = crypto.rewrap_dek_new_password(dek, new_password)
    new_pwd_hash = hash_password(new_password)

    with db_conn.cursor() as cur:
        cur.execute(
            """
            UPDATE users SET password_hash = %s, kdf_salt = %s, wrapped_dek = %s, dek_nonce = %s
            WHERE id = %s
            """,
            (new_pwd_hash, new_salt, new_wrapped, new_nonce, user_id)
        )
        db_conn.commit()

    logger.info(f"Password changed successfully for user id {user_id}")
    return True


def rotate_recovery_key(db_conn, user_id: int, current_password: str) -> str:
    """
    Generate and save a new recovery key for the user, invalidating the previous one.
    Requires the current password to verify identity.
    """
    with db_conn.cursor() as cur:
        cur.execute("SELECT password_hash, kdf_salt, wrapped_dek, dek_nonce FROM users WHERE id = %s", (user_id,))
        row = cur.fetchone()

    if not row:
        raise ValueError("Användaren hittades inte.")

    pwd_hash = row[0]
    salt = row[1]
    wrapped_dek = row[2]
    dek_nonce = row[3]

    if not verify_password(pwd_hash, current_password):
        raise ValueError("Det nuvarande lösenordet är felaktigt.")

    kek = crypto.derive_kek(current_password, salt)
    dek = crypto.unwrap_dek(kek, wrapped_dek, dek_nonce)

    new_key = crypto.generate_recovery_key()
    rec_salt, rec_nonce, rec_wrapped = crypto.wrap_dek_for_recovery(new_key, dek)

    with db_conn.cursor() as cur:
        cur.execute(
            """
            UPDATE users SET recovery_wrapped_dek = %s, recovery_salt = %s, recovery_nonce = %s
            WHERE id = %s
            """,
            (rec_wrapped, rec_salt, rec_nonce, user_id)
        )
        db_conn.commit()

    logger.info(f"Recovery key rotated successfully for user id {user_id}")
    return new_key


def update_user_profile(db_conn, session: UserSession, new_profile_data: Dict[str, Any]):
    """Update and persist user's encrypted personal profile."""
    nonce, ciphertext = crypto.encrypt_payload(session.dek, new_profile_data)
    with db_conn.cursor() as cur:
        cur.execute(
            "UPDATE users SET encrypted_profile = %s, profile_nonce = %s WHERE id = %s",
            (ciphertext, nonce, session.user_id)
        )
        db_conn.commit()
    session.encrypted_profile = new_profile_data
    logger.info(f"Updated encrypted profile for user id {session.user_id}")


def delete_user_account(db_conn, user_id: int):
    """
    Permanently delete user account and all cascading health data.
    """
    with db_conn.cursor() as cur:
        # Delete user row (cascades to all health data tables via FOREIGN KEY ON DELETE CASCADE)
        cur.execute("DELETE FROM users WHERE id = %s", (user_id,))
        db_conn.commit()
    clear_remembered_session()
    logger.info(f"Permanently deleted user id {user_id} and all related health data.")


# --- K-4: OS Keyring Session Helpers ---

KEYRING_SERVICE_NAME = "HealthChatDesktop_Auth"


def save_remembered_session(email: str, dek: bytes):
    """Save user's encrypted DEK to OS Keyring (Windows Credential Manager)."""
    try:
        import keyring
        encoded_dek = base64.b64encode(dek).decode("ascii")
        keyring.set_password(KEYRING_SERVICE_NAME, email.lower().strip(), encoded_dek)
        logger.info(f"Saved session DEK to keyring for {mask_email(email)}")
    except Exception as e:
        logger.warning(f"Could not save session to keyring: {e}")


def load_remembered_session(email: str) -> Optional[bytes]:
    """Load user's DEK from OS Keyring."""
    try:
        import keyring
        val = keyring.get_password(KEYRING_SERVICE_NAME, email.lower().strip())
        if val:
            return base64.b64decode(val.encode("ascii"))
    except Exception as e:
        logger.warning(f"Could not load session from keyring: {e}")
    return None


def clear_remembered_session(email: Optional[str] = None):
    """Remove user's DEK from OS Keyring."""
    try:
        import keyring
        if email:
            try:
                keyring.delete_password(KEYRING_SERVICE_NAME, email.lower().strip())
            except Exception:
                pass
        logger.info("Cleared keyring session.")
    except Exception as e:
        logger.debug(f"Keyring clear exception: {e}")


def get_remembered_user_session(db_conn, email: str) -> Optional[UserSession]:
    """
    Attempt to restore a UserSession from OS Keyring for the given email.
    Verifies user exists in MariaDB and decrypts profile.
    """
    clean_email = email.lower().strip()
    dek = load_remembered_session(clean_email)
    if not dek:
        return None
    try:
        with db_conn.cursor() as cur:
            cur.execute("SELECT id, encrypted_profile, profile_nonce FROM users WHERE email = %s", (clean_email,))
            row = cur.fetchone()
        if not row:
            return None
        user_id = row[0]
        enc_profile = row[1]
        profile_nonce = row[2]
        profile_data = {}
        if enc_profile and profile_nonce:
            try:
                profile_data = crypto.decrypt_payload(dek, enc_profile, profile_nonce)
            except Exception:
                pass
        logger.info(f"Successfully restored session from keyring for user id {user_id}")
        return UserSession(user_id=user_id, email=clean_email, dek=bytearray(dek), encrypted_profile=profile_data)
    except Exception as e:
        logger.warning(f"Failed to restore session for {mask_email(clean_email)}: {e}")
        return None


def logout_user(email: str, session: Optional[UserSession] = None):
    """Log out user, clear remembered session from keyring, and zero out session DEK."""
    clear_remembered_session(email)
    if session:
        session.clear()


