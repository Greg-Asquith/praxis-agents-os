# apps/api/utils/security.py

"""
Security utilities for encryption, hashing, and token generation.

Provides:
- Fernet encryption/decryption for OAuth tokens and sensitive data
- SHA256 hashing for session tokens
- Secure random token generation
- Password hashing for password-based auth and recovery codes
- CSRF protection utilities
- Key rotation support
"""

import asyncio
import hashlib
import hmac
import logging
import secrets
import time

from cryptography.fernet import Fernet, InvalidToken, MultiFernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from pwdlib import PasswordHash

from core.exceptions.auth import AuthorizationError
from core.exceptions.general import CustomValueError
from core.settings import settings

logger = logging.getLogger(__name__)

_primary_fernet: Fernet | None = None
_encryption_key_ring: MultiFernet | None = None

# Password hashing context
password_hasher = PasswordHash.recommended()

# =============================================================================
# Token Generation
# =============================================================================


def create_session_token() -> str:
    """
    Generate a secure random session token.

    Returns:
        A URL-safe base64 encoded random token (43 characters)
    """
    return secrets.token_urlsafe(32)


def generate_invitation_token() -> str:
    """
    Generate a secure invitation token.

    Returns:
        A URL-safe base64 encoded random token (32 characters)
    """
    return secrets.token_urlsafe(24)


# =============================================================================
# Hashing Utilities
# =============================================================================


def hash_token(token: str) -> str:
    """
    Hash a token using SHA256 for secure storage.

    Args:
        token: The token to hash

    Returns:
        Hexadecimal digest of the SHA256 hash
    """
    if not token or not token.strip():
        raise CustomValueError("Token cannot be empty")
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def verify_token_hash(token: str, token_hash: str) -> bool:
    """
    Verify a token against its stored hash.

    Args:
        token: The plain token
        token_hash: The stored hash

    Returns:
        True if token matches hash, False otherwise
    """
    return secrets.compare_digest(hash_token(token), token_hash)


def derive_purpose_key(root: bytes, purpose: str) -> bytes:
    """Derive a stable, purpose-separated 32-byte key from root material."""
    if not root:
        raise CustomValueError("Key root cannot be empty")
    if not purpose.strip():
        raise CustomValueError("Key purpose cannot be empty")
    return HKDF(
        algorithm=hashes.SHA256(),
        length=32,
        salt=None,
        info=purpose.encode("utf-8"),
    ).derive(root)


# =============================================================================
# Encryption Utilities (Fernet)
# =============================================================================


def configure_application_encryption_keys(keys: tuple[str, ...]) -> None:
    """Atomically install a validated newest-first Fernet key ring."""
    if not keys:
        raise CustomValueError("Application encryption key ring cannot be empty")
    try:
        instances = [Fernet(key.encode("ascii")) for key in keys]
    except (UnicodeEncodeError, ValueError) as exc:
        raise CustomValueError(
            "Application encryption key ring contains an invalid Fernet key",
            details={"error_type": type(exc).__name__},
        ) from exc

    global _primary_fernet, _encryption_key_ring
    _primary_fernet = instances[0]
    _encryption_key_ring = MultiFernet(instances)


def is_encrypted_with_primary(token: str) -> bool:
    """Return whether a token authenticates with the newest configured key."""
    primary = _require_primary_fernet()
    try:
        primary.decrypt(token.encode("utf-8"))
    except InvalidToken:
        return False
    return True


def encrypt_data(data: str) -> str:
    """
    Encrypt sensitive data using Fernet encryption.

    Args:
        data: The plaintext data to encrypt

    Returns:
        Base64 encoded encrypted data

    Raises:
        ValueError: If encryption fails
    """
    try:
        encrypted_bytes = _require_primary_fernet().encrypt(data.encode("utf-8"))
        return encrypted_bytes.decode("utf-8")
    except Exception as e:
        logger.error("Encryption failed", exc_info=True)
        raise CustomValueError(
            "Encryption failed",
            details={"error_type": type(e).__name__},
        ) from e


def decrypt_data(encrypted_data: str) -> str:
    """
    Decrypt data using Fernet decryption with key rotation support.

    Args:
        encrypted_data: The base64 encoded encrypted data

    Returns:
        The decrypted plaintext

    Raises:
        ValueError: If decryption fails with all available keys
    """
    try:
        decrypted_bytes = _require_encryption_key_ring().decrypt(encrypted_data.encode("utf-8"))
        return decrypted_bytes.decode("utf-8")
    except Exception as exc:
        raise CustomValueError(
            "Failed to decrypt data with any available key",
            details={"error_type": type(exc).__name__},
        ) from exc


def _require_primary_fernet() -> Fernet:
    if _primary_fernet is None:
        raise CustomValueError("Application encryption keys have not been loaded")
    return _primary_fernet


def _require_encryption_key_ring() -> MultiFernet:
    if _encryption_key_ring is None:
        raise CustomValueError("Application encryption keys have not been loaded")
    return _encryption_key_ring


if configured_keys := settings.application_encryption_keys:
    configure_application_encryption_keys(configured_keys)


# =============================================================================
# Password Hashing
# =============================================================================


def hash_password(password: str) -> str:
    """
    Hash a password using the configured password hasher.

    Args:
        password: The plaintext password

    Returns:
        The password hash
    """
    return password_hasher.hash(password)


def verify_password_hash(plain_password: str, hashed_password: str) -> bool:
    """
    Verify a password against its stored hash.

    Args:
        plain_password: The plaintext password
        hashed_password: The stored hash

    Returns:
        True if password is correct, False otherwise
    """
    if not hashed_password:
        return False
    try:
        return password_hasher.verify(plain_password, hashed_password)
    except Exception:
        # A malformed/corrupt stored hash otherwise looks like a wrong password.
        logger.warning("Password verification failed due to an invalid stored hash", exc_info=True)
        return False


async def hash_password_async(password: str) -> str:
    """Hash one password without blocking the event loop."""
    return await asyncio.to_thread(hash_password, password)


async def verify_password_hash_async(plain_password: str, hashed_password: str) -> bool:
    """Verify one password without blocking the event loop."""
    return await asyncio.to_thread(verify_password_hash, plain_password, hashed_password)


async def hash_passwords_async(passwords: list[str]) -> list[str]:
    """Hash a bounded password list in one worker-thread call."""
    return await asyncio.to_thread(lambda: [hash_password(password) for password in passwords])


async def matching_password_hash_index_async(
    plain_password: str,
    hashed_passwords: list[str],
) -> int | None:
    """Find a matching hash in one worker-thread call."""

    def find_match() -> int | None:
        for index, hashed_password in enumerate(hashed_passwords):
            if verify_password_hash(plain_password, hashed_password):
                return index
        return None

    return await asyncio.to_thread(find_match)


# =============================================================================
# HMAC and Signature Verification
# =============================================================================


def create_hmac_signature(data: str, secret: str) -> str:
    """
    Create HMAC-SHA256 signature for webhook verification.

    Args:
        data: The data to sign
        secret: The secret key

    Returns:
        Hexadecimal HMAC signature
    """
    return hmac.new(secret.encode("utf-8"), data.encode("utf-8"), hashlib.sha256).hexdigest()


def verify_hmac_signature(data: str, signature: str, secret: str) -> bool:
    """
    Verify HMAC-SHA256 signature.

    Args:
        data: The original data
        signature: The signature to verify
        secret: The secret key

    Returns:
        True if signature is valid, False otherwise
    """
    expected_signature = create_hmac_signature(data, secret)
    return secrets.compare_digest(signature, expected_signature)


# =============================================================================
# CSRF Protection — Session-Bound Signed Tokens
# =============================================================================

# Maximum age for CSRF tokens — matches session duration so the token
# stays valid for the entire session lifetime.  The token is already
# session-bound (HMAC-signed with a session-hash prefix), so the expiry
# window does not need to be shorter than the session itself.
CSRF_TOKEN_MAX_AGE = settings.SESSION_DURATION_DAYS * 86400


def _session_hash_prefix(session_token: str) -> str:
    """Derive a short, stable fingerprint from the raw session token."""
    return hashlib.sha256(session_token.encode("utf-8")).hexdigest()[:16]


def generate_csrf_token(session_token: str) -> str:
    """
    Generate a session-bound, HMAC-signed CSRF token.

    Format: ``{session_hash_prefix}.{timestamp}.{hmac_signature}``

    The token is bound to the session via a hash prefix of the raw session
    token.  The middleware can verify the binding without a DB lookup by
    hashing the session cookie and comparing prefixes.

    Args:
        session_token: The raw session token (from the session cookie).

    Returns:
        A signed CSRF token string.
    """
    prefix = _session_hash_prefix(session_token)
    timestamp = str(int(time.time()))
    payload = f"{prefix}:{timestamp}"
    signature = create_hmac_signature(payload, settings.SECRET_KEY.get_secret_value())
    return f"{prefix}.{timestamp}.{signature}"


def verify_csrf_token(
    csrf_token: str,
    session_token: str,
    max_age: int = CSRF_TOKEN_MAX_AGE,
) -> bool:
    """
    Verify a session-bound CSRF token.

    Checks:
    1. Token structure (three dot-separated parts).
    2. Timestamp is within *max_age* seconds.
    3. Session hash prefix matches the current session cookie.
    4. HMAC signature is valid (prevents forgery).

    Args:
        csrf_token: The CSRF token from the ``X-CSRF-Token`` header.
        session_token: The raw session token from the ``session`` cookie.
        max_age: Maximum age in seconds (default 24 h).

    Returns:
        True if valid.

    Raises:
        AuthorizationError on any validation failure.
    """
    parts = csrf_token.split(".")
    if len(parts) != 3:
        raise AuthorizationError(
            "Invalid CSRF token",
            details={"reason": "bad format"},
        )

    token_prefix, timestamp_str, signature = parts

    # --- timestamp ---
    try:
        timestamp = int(timestamp_str)
    except ValueError as exc:
        raise AuthorizationError(
            "Invalid CSRF token",
            details={"reason": "bad timestamp"},
        ) from exc
    if int(time.time()) - timestamp > max_age:
        raise AuthorizationError(
            "CSRF token expired",
            details={"reason": "expired"},
        )

    # --- session binding ---
    expected_prefix = _session_hash_prefix(session_token)
    if not secrets.compare_digest(token_prefix, expected_prefix):
        raise AuthorizationError(
            "Invalid CSRF token",
            details={"reason": "session mismatch"},
        )

    # --- HMAC signature ---
    payload = f"{token_prefix}:{timestamp_str}"
    expected_signature = create_hmac_signature(payload, settings.SECRET_KEY.get_secret_value())
    if not secrets.compare_digest(signature, expected_signature):
        raise AuthorizationError(
            "Invalid CSRF token",
            details={"reason": "signature mismatch"},
        )

    return True
