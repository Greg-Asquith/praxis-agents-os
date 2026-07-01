# apps/api/services/storage/providers/unavailable.py

"""Explicit placeholders for configured cloud providers not implemented yet."""

from datetime import timedelta

from services.storage.domain import SignedDownload, SignedUpload, StorageObjectRef, StoredObject
from services.storage.errors import StorageProviderUnavailableError


class UnavailableStorageProvider:
    """Provider adapter used when a configured storage backend is pending."""

    def __init__(self, provider_key: str) -> None:
        self.provider_key = provider_key

    def _raise(self, operation: str) -> None:
        raise StorageProviderUnavailableError(
            f"Storage provider '{self.provider_key}' is not implemented yet",
            provider_key=self.provider_key,
            operation=operation,
        )

    async def put_object(
        self,
        ref: StorageObjectRef,
        data: bytes,
        *,
        content_type: str | None = None,
        cache_control: str | None = None,
        metadata: dict[str, str] | None = None,
    ) -> StoredObject:
        self._raise("put_object")

    async def get_object(self, ref: StorageObjectRef) -> bytes:
        self._raise("get_object")

    async def stat_object(self, ref: StorageObjectRef) -> StoredObject | None:
        self._raise("stat_object")

    async def delete_object(self, ref: StorageObjectRef) -> bool:
        self._raise("delete_object")

    async def create_signed_upload(
        self,
        ref: StorageObjectRef,
        *,
        content_type: str,
        expires_in: timedelta,
    ) -> SignedUpload:
        self._raise("create_signed_upload")

    async def create_signed_download(
        self,
        ref: StorageObjectRef,
        *,
        expires_in: timedelta,
        force_download: bool = False,
        filename: str | None = None,
    ) -> SignedDownload:
        self._raise("create_signed_download")

    def public_url(self, ref: StorageObjectRef) -> str | None:
        self._raise("public_url")

    def require_valid_upload_signature(
        self,
        ref: StorageObjectRef,
        *,
        expires: int,
        signature: str,
        content_type: str,
    ) -> None:
        self._raise("require_valid_upload_signature")

    def require_valid_download_signature(
        self,
        ref: StorageObjectRef,
        *,
        expires: int,
        signature: str,
        force_download: bool = False,
        filename: str = "",
    ) -> None:
        self._raise("require_valid_download_signature")
