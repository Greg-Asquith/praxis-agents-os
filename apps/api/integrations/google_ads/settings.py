# apps/api/integrations/google_ads/settings.py

"""Google Ads-owned runtime configuration."""

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class GoogleAdsSettings(BaseSettings):
    """Environment-backed settings required only by the Google Ads provider."""

    GOOGLE_ADS_OAUTH_CLIENT_ID: str = ""
    GOOGLE_ADS_OAUTH_CLIENT_SECRET: SecretStr = SecretStr("")

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


google_ads_settings = GoogleAdsSettings()
