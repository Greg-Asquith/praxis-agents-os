# apps/api/integrations/outlook_mail/settings.py

"""Outlook Mail-owned runtime configuration."""

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class OutlookMailSettings(BaseSettings):
    """Environment-backed settings required only by Outlook Mail."""

    OUTLOOK_MAIL_OAUTH_CLIENT_ID: str = ""
    OUTLOOK_MAIL_OAUTH_CLIENT_SECRET: SecretStr = SecretStr("")
    OUTLOOK_MAIL_OAUTH_TENANT: str = ""
    OUTLOOK_MAIL_ATTACHMENT_MAX_BYTES: int = Field(default=26_214_400, gt=0)

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


outlook_mail_settings = OutlookMailSettings()
