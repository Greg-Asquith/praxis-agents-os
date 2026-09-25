# apps/api/integrations/meta_ads/settings.py

"""Meta Ads deployment configuration."""

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class MetaAdsSettings(BaseSettings):
    META_ADS_INSIGHTS_POLL_SECONDS: int = Field(default=90, ge=1, le=120)
    META_ADS_INSIGHTS_MAX_ROWS: int = Field(default=1_000, ge=1, le=100_000)
    META_ADS_APP_ID: str = ""
    META_ADS_APP_SECRET: SecretStr | None = None

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")


meta_ads_settings = MetaAdsSettings()
