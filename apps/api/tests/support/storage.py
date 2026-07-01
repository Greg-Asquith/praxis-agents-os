# apps/api/tests/support/storage.py

"""Storage test helpers."""

from services.storage import factory as storage_factory


def reset_storage_provider_cache() -> None:
    """Clear the storage provider singleton after tests patch storage settings."""
    with storage_factory._storage_lock:
        storage_factory._storage_provider = None
        storage_factory._storage_provider_key = None
