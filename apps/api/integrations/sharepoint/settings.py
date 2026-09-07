# apps/api/integrations/sharepoint/settings.py

"""SharePoint-owned runtime configuration."""

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class SharePointSettings(BaseSettings):
    """Environment-backed settings required only by SharePoint."""

    SHAREPOINT_OAUTH_CLIENT_ID: str = ""
    SHAREPOINT_OAUTH_CLIENT_SECRET: SecretStr = SecretStr("")
    SHAREPOINT_OAUTH_TENANT: str = ""
    SHAREPOINT_DISCOVERY_MAX_SITES: int = Field(default=50, ge=1, le=200)

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


sharepoint_settings = SharePointSettings()
