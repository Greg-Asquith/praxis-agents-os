# apps/api/tests/support/storage.py

"""Storage test helpers."""

from types import SimpleNamespace

from services.storage import factory as storage_factory
from services.storage.providers.gcs import GcsStorageProvider


def reset_storage_provider_cache() -> None:
    """Clear the storage provider singleton after tests patch storage settings."""
    with storage_factory._storage_lock:
        storage_factory._storage_provider = None
        storage_factory._storage_provider_key = None


class _FakeGcsClient:
    def bucket(self, name: str) -> SimpleNamespace:
        return SimpleNamespace(name=name)


def fake_gcs_storage_provider() -> GcsStorageProvider:
    """Returns a GCS provider for code that only builds refs and URIs, never calls GCS."""
    return GcsStorageProvider(
        public_bucket_name="praxis-public",
        workspace_bucket_prefix="praxis-test",
        workspace_bucket_location="EU",
        project_id="video-test",
        client=_FakeGcsClient(),
    )
