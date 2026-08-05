# apps/api/core/settings/security.py

"""Security secrets, cookie, lockout, and token lifetime settings."""

import json
from typing import Annotated

from cryptography.fernet import Fernet
from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import NoDecode


class SecuritySettingsMixin:
    # Super Admin Override
    SUPER_ADMIN_EMAILS: str = Field(
        default="", description="Comma-separated list of super admin email addresses"
    )

    # Security Configuration
    SECRET_KEY: SecretStr = Field(min_length=32, description="Secret key for session signing")
    # python3 -c "import secrets; print(secrets.token_urlsafe(64))"

    ENCRYPTION_KEYS: Annotated[list[SecretStr] | None, NoDecode] = Field(
        default=None,
        description="Newest-first Fernet application encryption key ring.",
    )
    ENCRYPTION_KEYS_SECRET_NAME: str | None = Field(
        default=None,
        description="Secret-provider name containing the application encryption key ring.",
    )
    # python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"

    SESSION_DURATION_DAYS: int = Field(
        default=7, ge=1, le=30, description="Session duration in days"
    )
    SECURE_COOKIES: bool = Field(default=True, description="Use secure cookies")
    COOKIE_DOMAIN: str | None = Field(default=None, description="Cookie domain")

    MAX_REQUEST_BODY_BYTES: int = Field(
        default=10485760,
        ge=1024,
        le=52428800,
        description="Global request body size limit (default 10MB for images)",
    )

    # Security lockout Configuration
    SECURITY_LOCKOUT_DURATION_MINUTES: int = Field(
        default=60, ge=5, le=1440, description="Account lockout duration in minutes"
    )
    SECURITY_SUSPICIOUS_ACTIVITY_THRESHOLD: int = Field(
        default=10,
        ge=3,
        le=50,
        description="Failed attempts threshold for suspicious activity",
    )

    # Auth Token TTLs
    PASSWORD_RESET_TOKEN_TTL_MINUTES: int = Field(
        default=60,
        ge=5,
        le=1440,
        description="Password reset/setup token expiry in minutes",
    )

    @property
    def super_admin_emails_list(self) -> list[str]:
        """Lowercased, trimmed list of super admin emails."""
        if not self.SUPER_ADMIN_EMAILS:
            return []
        return [e.strip().lower() for e in self.SUPER_ADMIN_EMAILS.split(",") if e.strip()]

    @field_validator("ENCRYPTION_KEYS", mode="before")
    @classmethod
    def parse_encryption_keys(cls, value):
        """Accept either a JSON array or a comma-separated key ring."""
        if value is None or isinstance(value, list):
            return value
        if not isinstance(value, str):
            raise TypeError("ENCRYPTION_KEYS must be a JSON array or comma-separated string")
        raw = value.strip()
        if raw.startswith("["):
            try:
                parsed = json.loads(raw)
            except json.JSONDecodeError as exc:
                raise ValueError("ENCRYPTION_KEYS contains invalid JSON") from exc
            if not isinstance(parsed, list):
                raise ValueError("ENCRYPTION_KEYS JSON value must be an array")
            return parsed
        return [entry.strip() for entry in raw.split(",") if entry.strip()]

    @field_validator("ENCRYPTION_KEYS")
    @classmethod
    def validate_encryption_keys(cls, value: list[SecretStr] | None) -> list[SecretStr] | None:
        """Reject empty or malformed application key rings."""
        if value is None:
            return None
        if not value:
            raise ValueError("ENCRYPTION_KEYS must contain at least one Fernet key")
        for entry in value:
            try:
                Fernet(entry.get_secret_value().encode("ascii"))
            except (UnicodeEncodeError, ValueError) as exc:
                raise ValueError(f"Invalid Fernet key in ENCRYPTION_KEYS: {exc}") from exc
        return value

    @model_validator(mode="after")
    def validate_application_encryption_source(self):
        """Require one unambiguous source for the application key ring."""
        if self.ENCRYPTION_KEYS_SECRET_NAME is not None:
            self.ENCRYPTION_KEYS_SECRET_NAME = self.ENCRYPTION_KEYS_SECRET_NAME.strip() or None
        if self.ENCRYPTION_KEYS_SECRET_NAME is not None and self.ENCRYPTION_KEYS is not None:
            raise ValueError(
                "Set ENCRYPTION_KEYS_SECRET_NAME or an inline application encryption "
                "key source, not both"
            )
        if self.ENCRYPTION_KEYS is None and self.ENCRYPTION_KEYS_SECRET_NAME is None:
            raise ValueError("Configure ENCRYPTION_KEYS or ENCRYPTION_KEYS_SECRET_NAME")
        if (
            self.ENCRYPTION_KEYS_SECRET_NAME is not None
            and getattr(self, "ENVIRONMENT", None) == "local"
        ):
            raise ValueError("ENCRYPTION_KEYS_SECRET_NAME is not supported in local mode")
        return self

    @property
    def application_encryption_keys(self) -> tuple[str, ...]:
        """Return the directly configured newest-first key ring."""
        if self.ENCRYPTION_KEYS is not None:
            return tuple(entry.get_secret_value() for entry in self.ENCRYPTION_KEYS)
        return ()

    @field_validator("COOKIE_DOMAIN", mode="before")
    @classmethod
    def normalize_cookie_domain(cls, v):
        """Use host-only cookies for localhost-style development origins."""
        if v is None:
            return None
        value = str(v).strip()
        if value in {"", "localhost", "127.0.0.1", "::1"}:
            return None
        return value
