# apps/api/integrations/outlook_calendar/settings.py

"""Outlook Calendar-owned runtime configuration."""

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class OutlookCalendarSettings(BaseSettings):
    """Environment-backed settings required only by Outlook Calendar."""

    OUTLOOK_CALENDAR_OAUTH_CLIENT_ID: str = ""
    OUTLOOK_CALENDAR_OAUTH_CLIENT_SECRET: SecretStr = SecretStr("")
    OUTLOOK_CALENDAR_OAUTH_TENANT: str = ""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


outlook_calendar_settings = OutlookCalendarSettings()
