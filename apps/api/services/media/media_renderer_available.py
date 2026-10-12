# apps/api/services/media/media_renderer_available.py

"""Reports whether this deployment can run media renderer operations."""

from core.settings import settings
from services.storage.factory import get_storage_provider

# Providers whose signed URLs the renderer can use. Azure and S3 adapters are pending.
RENDERER_STORAGE_PROVIDERS = frozenset({"gcs", "local_fs"})


def media_renderer_available() -> bool:
    """Checks the renderer is configured and the storage provider can stage for it."""
    return (
        settings.MEDIA_RENDERER_URL is not None
        and get_storage_provider().provider_key in RENDERER_STORAGE_PROVIDERS
    )
