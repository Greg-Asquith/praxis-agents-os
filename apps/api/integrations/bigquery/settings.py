# apps/api/integrations/bigquery/settings.py

"""BigQuery-owned provider limits."""

from typing import Final

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

BIGQUERY_DISCOVERY_PAGE_SIZE: Final = 1000
BIGQUERY_TABLE_LIST_PAGE_SIZE: Final = 1000


class BigQuerySettings(BaseSettings):
    """Environment-backed limits used only by the BigQuery provider."""

    BIGQUERY_SCHEMA_SYNC_MAX_TABLES: int = Field(default=500, ge=1)
    BIGQUERY_SCHEMA_SYNC_TIMEOUT_SECONDS: int = Field(default=900, ge=60, le=3600)
    BIGQUERY_MAX_BYTES_BILLED: int = Field(default=1024**3, ge=1)
    BIGQUERY_MAX_RESULT_CHARS: int = Field(default=16_000, ge=1000)
    BIGQUERY_QUERY_TIMEOUT_SECONDS: int = Field(default=60, ge=1, le=300)

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


bigquery_settings = BigQuerySettings()
