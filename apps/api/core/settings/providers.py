# apps/api/core/settings/providers.py

"""Provider selection settings for infrastructure and runtime capabilities."""

from typing import Literal

from pydantic import Field

from core.storage_buckets import (
    LOCAL_WORKSPACE_BUCKET_PREFIX,
    WORKSPACE_BUCKET_PREFIX_MAX_LENGTH,
)


class ProviderSettingsMixin:
    # Provider Configuration
    CLOUD_PROVIDER: Literal["local", "gcp", "azure", "aws"] = Field(
        default="gcp",
        description="Hosting cloud provider. Runtime capability axes such as storage and email are selected independently.",
    )
    SECRET_PROVIDER: Literal[
        "local", "gcp_secret_manager", "azure_key_vault", "aws_secrets_manager"
    ] = Field(
        default="local",
        description="Provider used for application-managed secret references.",
    )
    STORAGE_PROVIDER: Literal["local_fs", "gcs", "azure_blob", "s3"] = Field(
        default="gcs",
        description="Application-managed object storage provider.",
    )
    EMAIL_PROVIDER: Literal["console", "disabled", "ses", "smtp", "sendgrid"] = Field(
        default="ses",
        description="Email delivery provider.",
    )
    LOCAL_STORAGE_ROOT: str = Field(
        default=".local/storage",
        description="Root for local filesystem storage when STORAGE_PROVIDER=local_fs.",
    )
    WORKSPACE_BUCKET_PREFIX: str = Field(
        default=LOCAL_WORKSPACE_BUCKET_PREFIX,
        min_length=1,
        max_length=WORKSPACE_BUCKET_PREFIX_MAX_LENGTH,
        pattern=r"^[a-z0-9](?:[a-z0-9-]*[a-z0-9])?$",
        description=(
            "Deployment-unique lowercase prefix for private workspace buckets/containers."
        ),
    )
    LOCAL_SECRET_STORE_PATH: str = Field(
        default=".local/secrets.enc.json",
        description="Encrypted secret-store file used only when SECRET_PROVIDER=local.",
    )
