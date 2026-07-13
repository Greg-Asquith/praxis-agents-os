# apps/api/integrations/gmail/settings.py

"""Gmail-owned runtime configuration."""

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class GmailSettings(BaseSettings):
    """Environment-backed settings required only by the Gmail provider."""

    GMAIL_OAUTH_CLIENT_ID: str = ""
    GMAIL_OAUTH_CLIENT_SECRET: SecretStr = SecretStr("")

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


gmail_settings = GmailSettings()
