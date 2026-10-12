# apps/api/core/settings/media.py

"""Media renderer settings."""

from typing import Literal

from pydantic import Field, SecretStr, field_validator, model_validator


class MediaSettingsMixin:
    MEDIA_RENDERER_URL: str | None = Field(
        default=None,
        description="Base URL of the isolated media renderer. Unset makes renderer tools unavailable.",
    )
    MEDIA_RENDERER_AUTH: Literal["google_id_token", "shared_secret", "none"] = Field(
        default="google_id_token",
        description=(
            "How the API authenticates to the renderer: a Google ID token for Cloud Run IAM, "
            "a shared secret on a private network, or none (local only)."
        ),
    )
    MEDIA_RENDERER_SHARED_SECRET: SecretStr = Field(
        default=SecretStr(""),
        description="Bearer secret the renderer also holds as RENDERER_SHARED_SECRET.",
    )
    MEDIA_RENDERER_TIMEOUT_SECONDS: int = Field(
        default=900,
        ge=30,
        le=3000,
        description="Total time one renderer operation may take, transfers included.",
    )
    MEDIA_RENDERER_MAX_OUTPUT_BYTES: int = Field(
        default=524288000,
        ge=1048576,
        le=5368709120,
        description="Largest single file a renderer operation may write (500 MiB).",
    )
    MEDIA_STAGING_URL_TTL_SECONDS: int = Field(
        default=1800,
        ge=60,
        le=7200,
        description="Lifetime of a renderer operation's signed URLs; at least the timeout + 60.",
    )
    MEDIA_RENDERER_LOCAL_STORAGE_URL: str = Field(
        default="http://host.docker.internal:8000",
        description="Local only: the API origin as the renderer container reaches it.",
    )

    @field_validator("MEDIA_RENDERER_URL", mode="before")
    @classmethod
    def normalize_media_renderer_url(cls, value):
        if value is None or (isinstance(value, str) and not value.strip()):
            return None
        value = str(value).strip()
        if not value.startswith(("http://", "https://")):
            raise ValueError("MEDIA_RENDERER_URL must start with http:// or https://")
        return value.rstrip("/")

    @model_validator(mode="after")
    def validate_staging_urls_outlive_renders(self):
        """Rejects signed output URLs that could expire before a render uploads."""
        if self.MEDIA_STAGING_URL_TTL_SECONDS < self.MEDIA_RENDERER_TIMEOUT_SECONDS + 60:
            raise ValueError(
                "MEDIA_STAGING_URL_TTL_SECONDS must be at least MEDIA_RENDERER_TIMEOUT_SECONDS + 60"
            )
        return self

    @model_validator(mode="after")
    def validate_renderer_shared_secret(self):
        """Requires a long secret when the renderer authenticates callers by one."""
        if (
            self.MEDIA_RENDERER_AUTH == "shared_secret"
            and len(self.MEDIA_RENDERER_SHARED_SECRET.get_secret_value()) < 32
        ):
            raise ValueError("MEDIA_RENDERER_SHARED_SECRET must be at least 32 characters")
        return self
