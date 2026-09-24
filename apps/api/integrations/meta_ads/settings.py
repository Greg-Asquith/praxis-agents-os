# apps/api/integrations/meta_ads/settings.py

"""Meta Ads deployment configuration."""

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class MetaAdsSettings(BaseSettings):
    META_ADS_APP_ID: str = ""
    META_ADS_APP_SECRET: SecretStr | None = None

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")


meta_ads_settings = MetaAdsSettings()
