# apps/api/integrations/meta_ads/settings.py

"""Meta Ads deployment configuration."""

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class MetaAdsSettings(BaseSettings):
    META_ADS_INSIGHTS_POLL_SECONDS: int = Field(default=90, ge=1, le=120)
    META_ADS_INSIGHTS_MAX_ROWS: int = Field(default=1_000, ge=1, le=100_000)
    META_ADS_APP_SECRET: SecretStr | None = None
    # Meta accepts images up to 30 MB and videos up to 4 GB.
    META_ADS_IMAGE_MAX_UPLOAD_BYTES: int = Field(default=31_457_280, ge=1, le=31_457_280)
    META_ADS_VIDEO_MAX_UPLOAD_BYTES: int = Field(default=1_073_741_824, ge=1, le=4_294_967_296)
    META_ADS_VIDEO_PROCESSING_POLL_SECONDS: int = Field(default=120, ge=0, le=180)

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")


meta_ads_settings = MetaAdsSettings()
