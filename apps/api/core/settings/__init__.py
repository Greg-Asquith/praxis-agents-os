# apps/api/core/settings/__init__.py

"""
Application configuration using Pydantic BaseSettings.

Loads configuration from environment variables with validation.
All secrets should be loaded from environment variables or secret management systems.
"""

from pydantic import model_validator
from pydantic_settings import SettingsConfigDict

from core.settings.agents import AgentRunSettingsMixin
from core.settings.app import AppSettingsMixin
from core.settings.auth import AuthSettingsMixin
from core.settings.aws import AwsSettingsMixin
from core.settings.azure import AzureSettingsMixin
from core.settings.base import SettingsBase
from core.settings.database import DatabaseSettingsMixin
from core.settings.email import EmailSettingsMixin
from core.settings.files import FilesSettingsMixin
from core.settings.gcp import GcpSettingsMixin
from core.settings.jobs import JobsSettingsMixin
from core.settings.models import LLMSettingsMixin
from core.settings.providers import ProviderSettingsMixin
from core.settings.rate_limit import RateLimitSettingsMixin
from core.settings.security import SecuritySettingsMixin
from core.settings.urls import UrlSettingsMixin


class Settings(
    SettingsBase,
    AgentRunSettingsMixin,
    AppSettingsMixin,
    AuthSettingsMixin,
    AwsSettingsMixin,
    AzureSettingsMixin,
    DatabaseSettingsMixin,
    EmailSettingsMixin,
    FilesSettingsMixin,
    GcpSettingsMixin,
    JobsSettingsMixin,
    LLMSettingsMixin,
    ProviderSettingsMixin,
    RateLimitSettingsMixin,
    SecuritySettingsMixin,
    UrlSettingsMixin,
):
    """
    Combined global settings
    """

    @model_validator(mode="after")
    def validate_runtime_provider_config(self):
        """
        Validate provider-specific runtime config.

        Storage and email are explicit provider axes. Local-only providers must
        never be selected outside the local target, and cloud storage providers
        still require their provider-specific resource names.
        """
        if self.STORAGE_PROVIDER == "local_fs" and self.ENVIRONMENT != "local":
            raise ValueError("STORAGE_PROVIDER=local_fs is only allowed when ENVIRONMENT=local")

        if self.EMAIL_PROVIDER == "console" and self.ENVIRONMENT != "local":
            raise ValueError("EMAIL_PROVIDER=console is only allowed when ENVIRONMENT=local")

        if self.AGENT_RUN_HEARTBEAT_INTERVAL_SECONDS >= self.AGENT_RUN_LEASE_TTL_SECONDS:
            raise ValueError(
                "AGENT_RUN_HEARTBEAT_INTERVAL_SECONDS must be less than "
                "AGENT_RUN_LEASE_TTL_SECONDS"
            )

        if (
            self.AGENT_HISTORY_MAX_TURNS is not None
            and self.AGENT_HISTORY_KEEP_TURNS >= self.AGENT_HISTORY_MAX_TURNS
        ):
            raise ValueError(
                "AGENT_HISTORY_KEEP_TURNS must be less than AGENT_HISTORY_MAX_TURNS"
            )

        if self.STORAGE_PROVIDER == "azure_blob":
            required_fields = {
                "AZURE_STORAGE_ACCOUNT_NAME": self.AZURE_STORAGE_ACCOUNT_NAME,
                "AZURE_STORAGE_PUBLIC_CONTAINER": self.AZURE_STORAGE_PUBLIC_CONTAINER,
                "AZURE_STORAGE_PRIVATE_CONTAINER": self.AZURE_STORAGE_PRIVATE_CONTAINER,
            }
            missing_fields = [
                field_name
                for field_name, value in required_fields.items()
                if not (value or "").strip()
            ]
            if missing_fields:
                raise ValueError(
                    "STORAGE_PROVIDER=azure_blob requires the following settings: "
                    + ", ".join(missing_fields)
                )

        if self.STORAGE_PROVIDER == "gcs":
            required_fields = {
                "GCS_PUBLIC_ASSETS_BUCKET": self.GCS_PUBLIC_ASSETS_BUCKET,
                "GCS_PRIVATE_ASSETS_BUCKET": self.GCS_PRIVATE_ASSETS_BUCKET,
            }
            missing_fields = [
                field_name
                for field_name, value in required_fields.items()
                if not (value or "").strip()
            ]
            if missing_fields:
                raise ValueError(
                    "STORAGE_PROVIDER=gcs requires the following settings: "
                    + ", ".join(missing_fields)
                )

        if self.STORAGE_PROVIDER == "s3":
            required_fields = {
                "S3_PUBLIC_ASSETS_BUCKET": self.S3_PUBLIC_ASSETS_BUCKET,
                "S3_PRIVATE_ASSETS_BUCKET": self.S3_PRIVATE_ASSETS_BUCKET,
                "AWS_REGION": self.AWS_REGION,
                "PUBLIC_ASSETS_BASE_URL": self.PUBLIC_ASSETS_BASE_URL,
            }
            missing_fields = [
                field_name
                for field_name, value in required_fields.items()
                if not (value or "").strip()
            ]
            if missing_fields:
                raise ValueError(
                    "STORAGE_PROVIDER=s3 requires the following settings: "
                    + ", ".join(missing_fields)
                )

        return self

    @property
    def is_dev(self) -> bool:
        """Check if running in development mode."""
        return self.ENVIRONMENT in {"local", "development"}

    @property
    def is_prod(self) -> bool:
        """Check if running in production mode."""
        return self.ENVIRONMENT == "production"

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


# Global instance
settings = Settings()
