# apps/api/services/storage/providers/__init__.py

"""Concrete storage provider implementations."""

from services.storage.providers.local import LocalStorageProvider
from services.storage.providers.unavailable import UnavailableStorageProvider

__all__ = ["LocalStorageProvider", "UnavailableStorageProvider"]
