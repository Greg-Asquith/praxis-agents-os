# apps/api/services/storage/provider.py

"""Storage provider protocol."""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import timedelta
from typing import Protocol, runtime_checkable

from services.storage.domain import SignedDownload, SignedUpload, StorageObjectRef, StoredObject

STORAGE_STREAM_CHUNK_SIZE = 1024 * 1024


@runtime_checkable
class StorageProvider(Protocol):
    """Provider-neutral object storage surface used by application services."""

    provider_key: str

    async def put_object(
        self,
        ref: StorageObjectRef,
        data: bytes,
        *,
        content_type: str | None = None,
        cache_control: str | None = None,
        metadata: dict[str, str] | None = None,
    ) -> StoredObject:
        """Persist an object and return its metadata."""
        ...

    async def get_object(self, ref: StorageObjectRef) -> bytes:
        """Return object bytes."""
        ...

    def stream_object(self, ref: StorageObjectRef) -> AsyncIterator[bytes]:
        """Yield object bytes in chunks without buffering the whole object."""
        ...

    async def stat_object(self, ref: StorageObjectRef) -> StoredObject | None:
        """Return object metadata, or None when it is absent."""
        ...

    async def delete_object(self, ref: StorageObjectRef) -> bool:
        """Delete an object, returning whether anything was removed."""
        ...

    async def create_signed_upload(
        self,
        ref: StorageObjectRef,
        *,
        content_type: str,
        expires_in: timedelta,
    ) -> SignedUpload:
        """Create a direct-upload capability for this provider."""
        ...

    async def create_signed_download(
        self,
        ref: StorageObjectRef,
        *,
        expires_in: timedelta,
        force_download: bool = False,
        filename: str | None = None,
    ) -> SignedDownload:
        """Create a direct-download capability for this provider."""
        ...

    def public_url(self, ref: StorageObjectRef) -> str | None:
        """Return a stable public URL for public objects when available."""
        ...

    def require_valid_upload_signature(
        self,
        ref: StorageObjectRef,
        *,
        expires: int,
        signature: str,
        content_type: str,
    ) -> None:
        """Validate a provider-specific upload callback signature."""
        ...

    def require_valid_download_signature(
        self,
        ref: StorageObjectRef,
        *,
        expires: int,
        signature: str,
        force_download: bool = False,
        filename: str = "",
    ) -> None:
        """Validate a provider-specific download callback signature."""
        ...
