# apps/api/integrations/notion/settings.py

"""Notion-owned runtime configuration."""

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class NotionSettings(BaseSettings):
    """Environment-backed settings required only by Notion."""

    NOTION_OAUTH_CLIENT_ID: str = ""
    NOTION_OAUTH_CLIENT_SECRET: SecretStr = SecretStr("")

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


notion_settings = NotionSettings()
