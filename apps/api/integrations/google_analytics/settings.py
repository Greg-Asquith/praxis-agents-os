# apps/api/integrations/google_analytics/settings.py

"""Google Analytics-owned runtime configuration."""

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class GoogleAnalyticsSettings(BaseSettings):
    """Environment-backed settings required only by Google Analytics."""

    GOOGLE_ANALYTICS_OAUTH_CLIENT_ID: str = ""
    GOOGLE_ANALYTICS_OAUTH_CLIENT_SECRET: SecretStr = SecretStr("")

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


google_analytics_settings = GoogleAnalyticsSettings()
