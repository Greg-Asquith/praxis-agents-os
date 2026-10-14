# apps/api/core/settings/media.py

"""Media renderer settings."""

from typing import Literal

from pydantic import Field, SecretStr, field_validator, model_validator

# Providers whose signed URLs the renderer can use. Azure and S3 adapters are pending.
RENDERER_STORAGE_PROVIDERS = frozenset({"gcs", "local_fs"})


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
        default=2147483648,
        ge=1048576,
        le=5368709120,
        description=(
            "Largest single file a renderer operation may write (2 GiB, about 35 minutes of "
            "clip at the bitrate caps). The renderer's disk is its memory, shared with inputs."
        ),
    )
    MEDIA_STAGING_URL_TTL_SECONDS: int = Field(
        default=1800,
        ge=60,
        le=7200,
        description="Lifetime of a renderer operation's signed URLs; at least the timeout + 60.",
    )
    VIDEO_MAX_SOURCE_DURATION_SECONDS: int = Field(
        default=14400,
        ge=60,
        le=86400,
        description="Longest video a File may hold; longer videos fail processing (4 hours).",
    )
    VIDEO_TRANSCRIPTION_SPEECH_LOCATION: Literal["eu", "us"] = Field(
        default="eu",
        description="Speech-to-Text multi-region for Chirp 3 transcription on Vertex deployments.",
    )
    VIDEO_UNDERSTANDING_MODEL: str = Field(
        default="gemini-3.8-flash",
        description="Google catalog model that watches video for find_video_moments and ask_video.",
    )
    VIDEO_MOMENTS_WINDOW_SECONDS: int = Field(
        default=2400,
        ge=300,
        le=3600,
        description="Longest stretch of video one find_video_moments or ask_video call watches.",
    )
    VIDEO_SNAP_SHOT_TOLERANCE_MS: int = Field(
        default=700,
        ge=0,
        le=3000,
        description="How far a snapped cut may move to land on a shot boundary.",
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
