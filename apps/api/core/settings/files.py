# apps/api/core/settings/files.py

"""Upload file size limits & allowed file types."""

from pydantic import Field, field_validator


class FilesSettingsMixin:
    # Public asset serving (shared across storage providers)
    PUBLIC_ASSETS_BASE_URL: str | None = Field(
        default=None,
        description="Base URL for public assets (e.g. https://cdn.example.com). "
        "If not set, uses the storage provider's public URL.",
    )
    PUBLIC_ASSETS_CACHE_CONTROL: str = Field(
        default="public, max-age=31536000, immutable",
        description="Cache-Control for public assets",
    )

    @field_validator("PUBLIC_ASSETS_BASE_URL", mode="before")
    @classmethod
    def normalize_public_assets_base_url(cls, v):
        """Normalize PUBLIC_ASSETS_BASE_URL: treat unset markers as None, require
        an http(s) scheme when set (raising otherwise), and strip trailing slashes."""
        if v is None:
            return None
        if isinstance(v, str):
            s = v.strip()
            if s == "" or s.lower() in ("none", "null", "false", "0"):
                return None
            if not s.startswith(("http://", "https://")):
                raise ValueError("PUBLIC_ASSETS_BASE_URL must start with http:// or https://")
            return s.rstrip("/")
        return None

    # File Upload Limits (in bytes)
    MAX_FILE_SIZE_AVATAR: int = Field(
        default=5242880,
        ge=1048576,
        le=10485760,
        description="Max avatar file size (5MB)",
    )
    MAX_FILE_SIZE_ICON: int = Field(
        default=2097152,
        ge=524288,
        le=5242880,
        description="Max workspace icon file size (2MB)",
    )
    MAX_FILE_SIZE_DOCUMENT: int = Field(
        default=52428800,
        ge=1048576,
        le=104857600,
        description="Max document file size (50MB)",
    )
    MAX_SKILL_DOCUMENTS_PER_SKILL: int = Field(
        default=20,
        ge=1,
        le=100,
        description="Max documents per skill",
    )
    MAX_SKILL_DOC_MARKDOWN_BYTES: int = Field(
        default=2097152,
        ge=65536,
        le=10485760,
        description="Max size of converted skill-document markdown (2MB)",
    )
    MAX_FILE_SIZE_AGENT_FILE: int = Field(
        default=104857600,
        ge=1048576,
        le=524288000,
        description="Max agent-created file size (100MB)",
    )
    MAX_FILE_SIZE_AI_IMAGE: int = Field(
        default=10485760,
        ge=1048576,
        le=104857600,
        description="Max AI generated image file size (10MB)",
    )
    MAX_FILE_SIZE_AI_VIDEO: int = Field(
        default=104857600,
        ge=1048576,
        le=524288000,
        description="Max AI generated video file size (100MB)",
    )

    # File Types
    ALLOWED_IMAGE_TYPES: str = Field(
        default="image/jpeg,image/png,image/webp",
        description="Allowed image MIME types",
    )
    ALLOWED_ICON_TYPES: str = Field(
        default="image/jpeg,image/png,image/webp",
        description="Allowed raster icon MIME types",
    )
    ALLOWED_DOCUMENT_TYPES: str = Field(
        default="application/pdf,application/vnd.openxmlformats-officedocument.wordprocessingml.document,text/plain,text/markdown",
        description="Allowed document MIME types",
    )
    ALLOWED_VIDEO_TYPES: str = Field(default="video/mp4", description="Allowed video MIME types")

    # File Processing Settings
    ENABLE_IMAGE_PROCESSING: bool = Field(
        default=True, description="Enable automatic image processing and thumbnails"
    )
    AVATAR_SIZE: int = Field(default=512, ge=128, le=1024, description="Avatar image size (square)")
    ICON_SIZE: int = Field(default=256, ge=64, le=512, description="Icon image size (square)")
    THUMBNAIL_SIZES: str = Field(default="128,256", description="Comma-separated thumbnail sizes")
