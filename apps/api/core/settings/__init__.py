# apps/api/core/settings/__init__.py

"""
Application configuration using Pydantic BaseSettings.

Loads configuration from environment variables with validation.
All secrets should be loaded from environment variables or secret management systems.
"""

from ipaddress import ip_address
from urllib.parse import urlsplit

from pydantic import model_validator
from pydantic_settings import SettingsConfigDict

from core.settings.agents import AgentRunSettingsMixin
from core.settings.app import AppSettingsMixin
from core.settings.artifacts import ArtifactSettingsMixin
from core.settings.auth import AuthSettingsMixin
from core.settings.aws import AwsSettingsMixin
from core.settings.azure import AzureSettingsMixin
from core.settings.base import SettingsBase
from core.settings.database import DatabaseSettingsMixin
from core.settings.email import EmailSettingsMixin
from core.settings.embeddings import EmbeddingsSettingsMixin
from core.settings.files import FilesSettingsMixin
from core.settings.gcp import GcpSettingsMixin
from core.settings.integrations import IntegrationsSettingsMixin
from core.settings.jobs import JobsSettingsMixin
from core.settings.kb import KBSettingsMixin
from core.settings.memory import MemorySettingsMixin
from core.settings.models import LLMSettingsMixin
from core.settings.observability import ObservabilitySettingsMixin
from core.settings.providers import ProviderSettingsMixin
from core.settings.rate_limit import RateLimitSettingsMixin
from core.settings.retention import EventRetentionSettingsMixin
from core.settings.scratch import ScratchSettingsMixin
from core.settings.security import SecuritySettingsMixin
from core.settings.urls import UrlSettingsMixin
from core.storage_buckets import (
    LOCAL_WORKSPACE_BUCKET_PREFIX,
    S3_ACCOUNT_REGIONAL_UNSUPPORTED_REGIONS,
    s3_workspace_bucket_prefix_max_length,
)

_LOCAL_EXAMPLE_SECRET_KEY = "not-a-secret-local-development-secret-key-change-me"
_LOCAL_EXAMPLE_ENCRYPTION_KEY = "bm90LWEtc2VjcmV0LWxvY2FsLWRldi1rZXktMDAwMDA="


class Settings(
    SettingsBase,
    AgentRunSettingsMixin,
    AppSettingsMixin,
    ArtifactSettingsMixin,
    AuthSettingsMixin,
    AwsSettingsMixin,
    AzureSettingsMixin,
    DatabaseSettingsMixin,
    EmailSettingsMixin,
    EmbeddingsSettingsMixin,
    FilesSettingsMixin,
    GcpSettingsMixin,
    IntegrationsSettingsMixin,
    JobsSettingsMixin,
    KBSettingsMixin,
    MemorySettingsMixin,
    LLMSettingsMixin,
    ObservabilitySettingsMixin,
    ProviderSettingsMixin,
    RateLimitSettingsMixin,
    EventRetentionSettingsMixin,
    SecuritySettingsMixin,
    ScratchSettingsMixin,
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
        if self.ENVIRONMENT != "local":
            if self.SECRET_KEY.get_secret_value() == _LOCAL_EXAMPLE_SECRET_KEY:
                raise ValueError(
                    "SECRET_KEY uses the public .env.example placeholder; "
                    "set SECRET_KEY to a unique secret outside ENVIRONMENT=local"
                )
            if self.ENCRYPTION_KEY.get_secret_value() == _LOCAL_EXAMPLE_ENCRYPTION_KEY:
                raise ValueError(
                    "ENCRYPTION_KEY uses the public .env.example placeholder; "
                    "set ENCRYPTION_KEY to a newly generated Fernet key outside "
                    "ENVIRONMENT=local"
                )
            if not self.SECURE_COOKIES:
                raise ValueError("SECURE_COOKIES must be true outside ENVIRONMENT=local")

        if self.STORAGE_PROVIDER == "local_fs" and self.ENVIRONMENT != "local":
            raise ValueError("STORAGE_PROVIDER=local_fs is only allowed when ENVIRONMENT=local")

        if (
            self.ENVIRONMENT != "local"
            and self.WORKSPACE_BUCKET_PREFIX == LOCAL_WORKSPACE_BUCKET_PREFIX
        ):
            raise ValueError(
                "WORKSPACE_BUCKET_PREFIX must identify the deployment outside local environments"
            )

        if self.EMAIL_PROVIDER == "console" and self.ENVIRONMENT != "local":
            raise ValueError("EMAIL_PROVIDER=console is only allowed when ENVIRONMENT=local")

        if self.SECRET_PROVIDER == "local" and self.ENVIRONMENT != "local":
            raise ValueError("SECRET_PROVIDER=local is only allowed when ENVIRONMENT=local")

        if self.SECRET_PROVIDER == "gcp_secret_manager" and not (self.GCP_PROJECT_ID or "").strip():
            raise ValueError("SECRET_PROVIDER=gcp_secret_manager requires GCP_PROJECT_ID")

        if (
            self.SECRET_PROVIDER == "azure_key_vault"
            and not (self.AZURE_KEY_VAULT_URL or "").strip()
        ):
            raise ValueError("SECRET_PROVIDER=azure_key_vault requires AZURE_KEY_VAULT_URL")

        if self.SECRET_PROVIDER == "aws_secrets_manager" and not self.AWS_REGION.strip():
            raise ValueError("SECRET_PROVIDER=aws_secrets_manager requires AWS_REGION")

        if self.CREDENTIAL_MASTER_KEYS and self.ENVIRONMENT != "local":
            raise ValueError("CREDENTIAL_MASTER_KEYS is only allowed when ENVIRONMENT=local")

        if self.ARTIFACT_SHARE_DEFAULT_TTL_DAYS > self.ARTIFACT_SHARE_MAX_TTL_DAYS:
            raise ValueError(
                "ARTIFACT_SHARE_DEFAULT_TTL_DAYS must not exceed ARTIFACT_SHARE_MAX_TTL_DAYS"
            )

        if self.ARTIFACT_SHARING_ENABLED and self.ENVIRONMENT != "local":
            artifact_origin = urlsplit(self.ARTIFACT_ORIGIN)
            artifact_host = artifact_origin.hostname
            if not artifact_host:
                raise ValueError(
                    "ARTIFACT_ORIGIN is required when artifact sharing is enabled "
                    "outside local environments"
                )
            if artifact_origin.scheme != "https":
                raise ValueError(
                    "ARTIFACT_ORIGIN must use HTTPS when artifact sharing is enabled "
                    "outside local environments"
                )
            if not self.RATE_LIMIT_ENABLED:
                raise ValueError(
                    "RATE_LIMIT_ENABLED must be true when artifact sharing is enabled "
                    "outside local environments"
                )
            for setting_name, value in (
                ("APP_BASE_URL", self.APP_BASE_URL),
                ("FRONTEND_URL", self.FRONTEND_URL),
            ):
                app_host = urlsplit(value).hostname
                if app_host and _hosts_share_site(artifact_host, app_host):
                    raise ValueError(
                        "ARTIFACT_ORIGIN must use a distinct site from "
                        f"{setting_name} when artifact sharing is enabled"
                    )
            cookie_domain = (self.COOKIE_DOMAIN or "").lstrip(".").rstrip(".").lower()
            if cookie_domain and (
                artifact_host == cookie_domain or artifact_host.endswith(f".{cookie_domain}")
            ):
                raise ValueError(
                    "ARTIFACT_ORIGIN must not be covered by COOKIE_DOMAIN "
                    "when artifact sharing is enabled"
                )

        if (
            self.ENVIRONMENT != "local"
            and self.INTEGRATIONS_OAUTH_REDIRECT_URI
            and not self.INTEGRATIONS_OAUTH_REDIRECT_URI.startswith("https://")
        ):
            raise ValueError(
                "INTEGRATIONS_OAUTH_REDIRECT_URI must use HTTPS outside local environments"
            )

        if (
            self.METRICS_ENABLED
            and not self.METRICS_TOKEN
            and self.ENVIRONMENT not in {"local", "development"}
        ):
            raise ValueError(
                "METRICS_TOKEN must be set when METRICS_ENABLED=true outside local/development"
            )

        if self.AGENT_RUN_HEARTBEAT_INTERVAL_SECONDS >= self.AGENT_RUN_LEASE_TTL_SECONDS:
            raise ValueError(
                "AGENT_RUN_HEARTBEAT_INTERVAL_SECONDS must be less than AGENT_RUN_LEASE_TTL_SECONDS"
            )

        if (
            self.AGENT_HISTORY_MAX_TURNS is not None
            and self.AGENT_HISTORY_KEEP_TURNS >= self.AGENT_HISTORY_MAX_TURNS
        ):
            raise ValueError("AGENT_HISTORY_KEEP_TURNS must be less than AGENT_HISTORY_MAX_TURNS")

        if self.STORAGE_PROVIDER == "azure_blob":
            required_fields = {
                "AZURE_STORAGE_ACCOUNT_NAME": self.AZURE_STORAGE_ACCOUNT_NAME,
                "AZURE_STORAGE_PUBLIC_CONTAINER": self.AZURE_STORAGE_PUBLIC_CONTAINER,
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
                "GCP_PROJECT_ID": self.GCP_PROJECT_ID,
                "GCS_PUBLIC_ASSETS_BUCKET": self.GCS_PUBLIC_ASSETS_BUCKET,
                "GCS_WORKSPACE_BUCKET_LOCATION": self.GCS_WORKSPACE_BUCKET_LOCATION,
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
                "AWS_REGION": self.AWS_REGION,
                "AWS_ACCOUNT_ID": self.AWS_ACCOUNT_ID,
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
            if self.AWS_REGION in S3_ACCOUNT_REGIONAL_UNSUPPORTED_REGIONS:
                raise ValueError(
                    "STORAGE_PROVIDER=s3 requires an AWS region that supports "
                    "account-regional buckets"
                )
            s3_prefix_max_length = s3_workspace_bucket_prefix_max_length(self.AWS_REGION)
            if len(self.WORKSPACE_BUCKET_PREFIX) > s3_prefix_max_length:
                raise ValueError(
                    "WORKSPACE_BUCKET_PREFIX must be at most "
                    f"{s3_prefix_max_length} characters for account-regional S3 buckets "
                    f"in {self.AWS_REGION}"
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


def _hosts_share_site(left: str, right: str) -> bool:
    """Conservatively approximate registrable-domain equality without a PSL."""
    left = left.rstrip(".").lower()
    right = right.rstrip(".").lower()
    return _site_suffix(left) == _site_suffix(right)


def _site_suffix(host: str) -> str:
    try:
        ip_address(host)
    except ValueError:
        labels = host.split(".")
        return ".".join(labels[-2:]) if len(labels) > 1 else host
    return host


# Global instance
settings = Settings()
