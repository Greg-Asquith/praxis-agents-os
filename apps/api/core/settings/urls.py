# apps/api/core/settings/urls.py

"""Application URL, CORS origin, and database URL settings."""

from pydantic import Field, field_validator


class UrlSettingsMixin:
    # URLs Configuration
    APP_BASE_URL: str = Field(
        default="http://localhost:8000", description="Base URL for the application"
    )
    API_V1_PREFIX: str = Field(default="/api/v1", description="API v1 prefix")
    ALLOWED_CORS_ORIGINS: str = Field(
        default="http://localhost:3000",
        description="Allowed CORS origins (comma-separated)",
    )
    FRONTEND_URL: str = Field(
        default="http://localhost:3000", description="Frontend application URL"
    )
    NEXTJS_INTERNAL_URL: str = Field(
        default="http://localhost:3000", description="Next.js internal URL"
    )

    @field_validator("APP_BASE_URL", "FRONTEND_URL", "NEXTJS_INTERNAL_URL")
    @classmethod
    def validate_http_url(cls, v):
        """Validate URL scheme and strip any trailing slash."""
        if not v.startswith(("http://", "https://")):
            raise ValueError("URL must start with http:// or https://")
        return v.rstrip("/")

    @field_validator("ALLOWED_CORS_ORIGINS")
    @classmethod
    def _reject_wildcard_cors_origins(cls, v: str) -> str:
        origins = [origin.strip() for origin in (v or "").split(",") if origin.strip()]
        for origin in origins:
            if origin == "*" or origin.startswith("*"):
                raise ValueError(
                    "ALLOWED_CORS_ORIGINS must list explicit origins; wildcard origins are not "
                    "allowed because CORS credentials are enabled."
                )
            if not origin.startswith(("http://", "https://")):
                raise ValueError(f"CORS origin must include an http(s) scheme: {origin!r}")
        return v

    @property
    def cors_origins_list(self) -> list[str]:
        """Get CORS origins as a list."""
        if not self.ALLOWED_CORS_ORIGINS:
            return []
        return [origin.strip() for origin in self.ALLOWED_CORS_ORIGINS.split(",") if origin.strip()]
