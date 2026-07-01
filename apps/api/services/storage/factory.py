# apps/api/services/storage/factory.py

"""Storage provider factory."""

from __future__ import annotations

import threading

from core.settings import settings
from services.storage.errors import StorageProviderUnavailableError
from services.storage.provider import StorageProvider
from services.storage.providers.local import LocalStorageProvider
from services.storage.providers.unavailable import UnavailableStorageProvider

_storage_provider: StorageProvider | None = None
_storage_provider_key: str | None = None
_storage_lock = threading.Lock()


def get_storage_provider() -> StorageProvider:
    """Return the singleton provider for the configured storage backend."""
    global _storage_provider, _storage_provider_key

    provider_key = settings.STORAGE_PROVIDER
    if _storage_provider is not None and _storage_provider_key == provider_key:
        return _storage_provider

    with _storage_lock:
        if _storage_provider is not None and _storage_provider_key == provider_key:
            return _storage_provider

        if provider_key == "local_fs":
            provider: StorageProvider = LocalStorageProvider.from_settings(settings)
        else:
            provider = UnavailableStorageProvider(provider_key)

        _storage_provider = provider
        _storage_provider_key = provider_key
        return provider


def get_local_storage_provider() -> LocalStorageProvider:
    """Return the local provider, or raise if another provider is active."""
    provider = get_storage_provider()
    if isinstance(provider, LocalStorageProvider):
        return provider
    raise StorageProviderUnavailableError(
        "Local filesystem storage is not enabled",
        provider_key=settings.STORAGE_PROVIDER,
        operation="get_local_storage_provider",
    )
