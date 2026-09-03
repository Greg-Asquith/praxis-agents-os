# apps/api/integrations/google_search_console/settings.py

"""Google Search Console-owned runtime configuration."""

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class GoogleSearchConsoleSettings(BaseSettings):
    """Environment-backed settings required only by Google Search Console."""

    GOOGLE_SEARCH_CONSOLE_OAUTH_CLIENT_ID: str = ""
    GOOGLE_SEARCH_CONSOLE_OAUTH_CLIENT_SECRET: SecretStr = SecretStr("")
    GOOGLE_SEARCH_CONSOLE_INDEXING_API_ENABLED: bool = False

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


google_search_console_settings = GoogleSearchConsoleSettings()
