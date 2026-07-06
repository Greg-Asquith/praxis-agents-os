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

import hashlib
import hmac
import logging
import secrets
import time

from cryptography.fernet import Fernet, InvalidToken
from pwdlib import PasswordHash

from core.exceptions.auth import AuthorizationError
from core.exceptions.general import CustomValueError
from core.settings import settings

logger = logging.getLogger(__name__)

# Initialize encryption with primary key
_primary_fernet = Fernet(settings.ENCRYPTION_KEY.get_secret_value().encode())

# For key rotation, we could have multiple keys (future enhancement)
_encryption_keys = [_primary_fernet]

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


# =============================================================================
# Encryption Utilities (Fernet)
# =============================================================================


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
        encrypted_bytes = _primary_fernet.encrypt(data.encode("utf-8"))
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
    # Try each encryption key (for key rotation support)
    last_error: Exception | None = None
    for fernet_instance in _encryption_keys:
        try:
            decrypted_bytes = fernet_instance.decrypt(encrypted_data.encode("utf-8"))
            return decrypted_bytes.decode("utf-8")
        except InvalidToken as e:
            # Try next key on invalid token (key rotation support)
            last_error = e
            continue
        except Exception as e:  # pragma: no cover
            last_error = e
            continue

    # All keys failed
    raise CustomValueError(
        "Failed to decrypt data with any available key",
        details={"error_type": type(last_error).__name__ if last_error else None},
    )


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
