# apps/api/core/settings/gcp.py

"""Google Cloud infrastructure provider settings."""

from pydantic import Field


class GcpSettingsMixin:
    # Google Cloud Platform Configuration
    GCP_PROJECT_ID: str | None = Field(default=None, description="GCP project ID")
    GCS_PUBLIC_ASSETS_BUCKET: str = Field(
        default="", description="GCS bucket for public assets (public-read)"
    )
    GCS_WORKSPACE_BUCKET_LOCATION: str = Field(
        default="",
        description=(
            "Immutable GCS location for workspace-private buckets. "
            "Required when STORAGE_PROVIDER=gcs."
        ),
    )
