# apps/api/core/settings/integrations.py

"""Integration engine and credential-vault settings."""

from pydantic import Field


class IntegrationsSettingsMixin:
    INTEGRATIONS_ENABLED_PROVIDERS: list[str] = Field(
        default_factory=list,
        description="Integration provider packages imported at process startup.",
    )
    INTEGRATIONS_TOKEN_REFRESH_LEEWAY_SECONDS: int = Field(
        default=120,
        gt=0,
        description="Seconds before expiry when OAuth credentials refresh proactively.",
    )
    INTEGRATIONS_HTTP_TIMEOUT_SECONDS: float = Field(
        default=30.0,
        gt=0,
        description="Per-request timeout for integration-provider HTTP calls.",
    )
    INTEGRATIONS_HTTP_RETRY_MAX_ATTEMPTS: int = Field(
        default=3,
        gt=0,
        description="Maximum attempts for retryable integration-provider HTTP calls.",
    )
    INTEGRATIONS_HTTP_RETRY_BACKOFF_FACTOR: float = Field(
        default=0.5,
        gt=0,
        description="Exponential backoff factor when Retry-After is absent.",
    )
    INTEGRATIONS_HTTP_RETRY_AFTER_CAP_SECONDS: int = Field(
        default=60,
        gt=0,
        description="Maximum Retry-After delay honored for integration-provider calls.",
    )
    CREDENTIAL_MASTER_KEY_SECRET_NAME: str = Field(
        default="credential-master-key",
        min_length=1,
        description="Secret-manager name containing credential root keys.",
    )
    CREDENTIAL_MASTER_KEYS: str | None = Field(
        default=None,
        description="Local-only comma-separated Fernet credential root keys, newest first.",
    )
