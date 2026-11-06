# apps/api/core/settings/data_science.py

"""Data science service settings."""

from typing import Literal

from pydantic import Field, SecretStr, field_validator, model_validator


class DataScienceSettingsMixin:
    DATA_SCIENCE_URL: str | None = Field(
        default=None,
        description="Base URL of the isolated data science service. Unset hides forecast_series.",
    )
    DATA_SCIENCE_AUTH: Literal["google_id_token", "shared_secret", "none"] = Field(
        default="google_id_token",
        description=(
            "How the API authenticates to the data science service: a Google ID token for "
            "Cloud Run IAM, a shared secret on a private network, or none (local only)."
        ),
    )
    DATA_SCIENCE_SHARED_SECRET: SecretStr = Field(
        default=SecretStr(""),
        description="Bearer secret the service also holds as RENDERER_SHARED_SECRET.",
    )
    DATA_SCIENCE_TIMEOUT_SECONDS: int = Field(
        default=300,
        ge=30,
        le=900,
        description="Longest one data science operation may run; the service's own limit.",
    )
    FORECAST_MAX_HISTORY_POINTS: int = Field(
        default=10_000,
        ge=16,
        le=32_768,
        description="Most history points one forecast_series call may send.",
    )
    FORECAST_MAX_HORIZON: int = Field(
        default=1_024,
        ge=1,
        le=1_024,
        description="Most steps one forecast_series call may forecast.",
    )
    FORECAST_MAX_COVARIATES: int = Field(
        default=8,
        ge=0,
        le=8,
        description="Most covariates one forecast_series call may send, besides holidays.",
    )

    @field_validator("DATA_SCIENCE_URL", mode="before")
    @classmethod
    def normalize_data_science_url(cls, value):
        if value is None or (isinstance(value, str) and not value.strip()):
            return None
        value = str(value).strip()
        if not value.startswith(("http://", "https://")):
            raise ValueError("DATA_SCIENCE_URL must start with http:// or https://")
        return value.rstrip("/")

    @model_validator(mode="after")
    def validate_data_science_shared_secret(self):
        """Requires a long secret when the service authenticates callers by one."""
        if (
            self.DATA_SCIENCE_AUTH == "shared_secret"
            and len(self.DATA_SCIENCE_SHARED_SECRET.get_secret_value()) < 32
        ):
            raise ValueError("DATA_SCIENCE_SHARED_SECRET must be at least 32 characters")
        return self
