# apps/api/core/settings/artifacts.py

"""Artifact creation and serving settings."""

from urllib.parse import urlsplit

from pydantic import Field, field_validator


class ArtifactSettingsMixin:
    ARTIFACT_ORIGIN: str = ""
    ARTIFACT_VIEW_URL_TTL_SECONDS: int = Field(default=300, ge=1, le=3600)
    ARTIFACT_MAX_CONTENT_BYTES: int = Field(
        default=1_048_576,
        ge=1024,
        le=10_485_760,
    )

    @field_validator("ARTIFACT_ORIGIN")
    @classmethod
    def validate_artifact_origin(cls, value: str) -> str:
        if not value:
            return ""
        parsed = urlsplit(value)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("ARTIFACT_ORIGIN must be an http(s) origin")
        if parsed.path not in {"", "/"} or parsed.query or parsed.fragment:
            raise ValueError("ARTIFACT_ORIGIN must not contain a path, query, or fragment")
        return f"{parsed.scheme}://{parsed.netloc}"
