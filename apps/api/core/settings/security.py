# apps/api/core/settings/security.py

"""Security secrets, cookie, lockout, and token lifetime settings."""

from cryptography.fernet import Fernet
from pydantic import Field, SecretStr, field_validator, model_validator


class SecuritySettingsMixin:
    # Super Admin Override
    SUPER_ADMIN_EMAILS: str = Field(
        default="", description="Comma-separated list of super admin email addresses"
    )

    # Security Configuration
    SECRET_KEY: SecretStr = Field(min_length=32, description="Secret key for session signing")
    # python3 -c "import secrets; print(secrets.token_urlsafe(64))"

    ENCRYPTION_KEY: SecretStr = Field(description="Fernet encryption key for tokens")
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

    # Scheduled Task Execution Configuration
    INTERNAL_SCHEDULE_TRIGGER_SECRET: str = Field(
        default="",
        description="Secret for scheduler -> Next.js internal schedule execution authentication (x-internal-secret header).",
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

    @model_validator(mode="after")
    def validate_internal_schedule_trigger_secret(self):
        """Require a non-empty secret in non-local/development environments.

        Uses a model validator (not a field validator) so that ENVIRONMENT —
        which is defined on a different settings mixin — is guaranteed to be
        populated regardless of field/MRO ordering.
        """
        environment = getattr(self, "ENVIRONMENT", None)
        if not self.INTERNAL_SCHEDULE_TRIGGER_SECRET and environment not in (
            "local",
            "development",
        ):
            raise ValueError(
                "INTERNAL_SCHEDULE_TRIGGER_SECRET must be set in non-local/development environments"
            )
        return self

    @field_validator("ENCRYPTION_KEY")
    @classmethod
    def validate_encryption_key(cls, v: SecretStr) -> SecretStr:
        """Validate encryption key format for Fernet."""
        try:
            # Try to create a Fernet instance to validate the key
            Fernet(v.get_secret_value().encode())
            return v
        except ValueError as e:
            raise ValueError(f"Invalid Fernet encryption key: {e}") from e

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
