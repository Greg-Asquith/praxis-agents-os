# apps/api/services/storage/providers/gcs.py

"""Google Cloud Storage provider for the storage contract."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

from services.storage.domain import (
    SignedDownload,
    SignedUpload,
    StorageBucket,
    StorageObjectRef,
    StoredObject,
)
from services.storage.errors import (
    StorageError,
    StorageNotFoundError,
    StorageProviderUnavailableError,
)
from services.storage.paths import build_content_disposition, quote_object_key
from services.storage.providers._common import (
    as_aware_datetime as _as_aware_datetime,
    require_content_type as _require_content_type,
    require_setting as _require_setting,
    string_metadata as _string_metadata,
)

if TYPE_CHECKING:
    from core.settings import Settings

try:  # pragma: no cover - exercised through provider-specific extras
    from google.cloud import storage as gcs_storage
except ImportError:  # pragma: no cover - base install intentionally omits SDKs
    gcs_storage = None

try:  # pragma: no cover - exercised through provider-specific extras
    from google.api_core import exceptions as gcs_exceptions
except ImportError:  # pragma: no cover - base install intentionally omits SDKs
    gcs_exceptions = None


class GcsStorageProvider:
    """Google Cloud Storage implementation of the provider-neutral contract."""

    provider_key = "gcs"

    def __init__(
        self,
        *,
        public_bucket_name: str,
        private_bucket_name: str,
        public_assets_base_url: str | None = None,
        public_cache_control: str | None = None,
        project_id: str | None = None,
        client: Any | None = None,
    ) -> None:
        self.public_bucket_name = _require_setting(
            public_bucket_name,
            "GCS_PUBLIC_ASSETS_BUCKET",
            provider_key=self.provider_key,
        )
        self.private_bucket_name = _require_setting(
            private_bucket_name,
            "GCS_PRIVATE_ASSETS_BUCKET",
            provider_key=self.provider_key,
        )
        self.public_assets_base_url = (
            public_assets_base_url.rstrip("/") if public_assets_base_url else None
        )
        self.public_cache_control = public_cache_control
        self.client = client if client is not None else self._create_client(project_id=project_id)
        self.public_bucket = self.client.bucket(self.public_bucket_name)
        self.private_bucket = self.client.bucket(self.private_bucket_name)

    @classmethod
    def from_settings(cls, settings: Settings) -> GcsStorageProvider:
        return cls(
            public_bucket_name=settings.GCS_PUBLIC_ASSETS_BUCKET,
            private_bucket_name=settings.GCS_PRIVATE_ASSETS_BUCKET,
            public_assets_base_url=settings.PUBLIC_ASSETS_BASE_URL,
            public_cache_control=settings.PUBLIC_ASSETS_CACHE_CONTROL,
            project_id=settings.GCP_PROJECT_ID,
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
        bucket = self._bucket(ref.bucket)
        blob = bucket.blob(ref.key)
        resolved_cache_control = cache_control
        if ref.bucket == StorageBucket.PUBLIC and resolved_cache_control is None:
            resolved_cache_control = self.public_cache_control
        blob.cache_control = resolved_cache_control
        blob.metadata = _string_metadata(metadata)

        try:
            await asyncio.to_thread(blob.upload_from_string, data, content_type=content_type)
        except Exception as exc:
            raise StorageError(
                "Failed to upload GCS object",
                provider_key=self.provider_key,
                operation="put_object",
                bucket=ref.bucket.value,
                object_key=ref.key,
                original_error=exc,
            ) from exc

        stored = await self.stat_object(ref)
        if stored is None:
            raise StorageNotFoundError(
                "Stored object could not be read after write",
                provider_key=self.provider_key,
                operation="put_object",
                bucket=ref.bucket.value,
                object_key=ref.key,
            )
        return stored

    async def get_object(self, ref: StorageObjectRef) -> bytes:
        blob = self._bucket(ref.bucket).blob(ref.key)
        try:
            exists = await asyncio.to_thread(blob.exists)
            if not exists:
                raise StorageNotFoundError(
                    "Storage object not found",
                    provider_key=self.provider_key,
                    operation="get_object",
                    bucket=ref.bucket.value,
                    object_key=ref.key,
                )
            return await asyncio.to_thread(blob.download_as_bytes)
        except StorageNotFoundError:
            raise
        except Exception as exc:
            raise StorageError(
                "Failed to download GCS object",
                provider_key=self.provider_key,
                operation="get_object",
                bucket=ref.bucket.value,
                object_key=ref.key,
                original_error=exc,
            ) from exc

    async def stat_object(self, ref: StorageObjectRef) -> StoredObject | None:
        blob = self._bucket(ref.bucket).blob(ref.key)
        try:
            await asyncio.to_thread(blob.reload)
        except Exception as exc:
            if _is_gcs_not_found(exc):
                return None
            raise StorageError(
                "Failed to read GCS object metadata",
                provider_key=self.provider_key,
                operation="stat_object",
                bucket=ref.bucket.value,
                object_key=ref.key,
                original_error=exc,
            ) from exc

        return StoredObject(
            ref=ref,
            size_bytes=int(blob.size or 0),
            etag=str(blob.etag or blob.md5_hash or blob.generation or ""),
            content_type=blob.content_type,
            cache_control=blob.cache_control,
            metadata=_string_metadata(blob.metadata),
            public_url=self.public_url(ref),
            updated_at=_as_aware_datetime(blob.updated),
        )

    async def delete_object(self, ref: StorageObjectRef) -> bool:
        blob = self._bucket(ref.bucket).blob(ref.key)
        try:
            exists = await asyncio.to_thread(blob.exists)
            if not exists:
                return False
            await asyncio.to_thread(blob.delete)
            return True
        except Exception as exc:
            raise StorageError(
                "Failed to delete GCS object",
                provider_key=self.provider_key,
                operation="delete_object",
                bucket=ref.bucket.value,
                object_key=ref.key,
                original_error=exc,
            ) from exc

    async def create_signed_upload(
        self,
        ref: StorageObjectRef,
        *,
        content_type: str,
        expires_in: timedelta,
    ) -> SignedUpload:
        normalized_content_type = _require_content_type(
            content_type, provider_key=self.provider_key, ref=ref
        )
        expires_at = datetime.now(UTC) + expires_in
        blob = self._bucket(ref.bucket).blob(ref.key)
        try:
            url = await asyncio.to_thread(
                blob.generate_signed_url,
                expiration=expires_at,
                method="PUT",
                content_type=normalized_content_type,
                version="v4",
            )
        except Exception as exc:
            raise StorageError(
                "Failed to create GCS signed upload URL",
                provider_key=self.provider_key,
                operation="create_signed_upload",
                bucket=ref.bucket.value,
                object_key=ref.key,
                original_error=exc,
            ) from exc
        return SignedUpload(
            ref=ref,
            url=str(url),
            headers={"content-type": normalized_content_type},
            expires_at=expires_at,
        )

    async def create_signed_download(
        self,
        ref: StorageObjectRef,
        *,
        expires_in: timedelta,
        force_download: bool = False,
        filename: str | None = None,
    ) -> SignedDownload:
        expires_at = datetime.now(UTC) + expires_in
        if ref.bucket == StorageBucket.PUBLIC:
            return SignedDownload(ref=ref, url=self.public_url(ref) or "", expires_at=expires_at)

        response_disposition = (
            build_content_disposition(filename or ref.key.rsplit("/", 1)[-1])
            if force_download
            else None
        )
        blob = self._bucket(ref.bucket).blob(ref.key)
        try:
            url = await asyncio.to_thread(
                blob.generate_signed_url,
                expiration=expires_at,
                method="GET",
                version="v4",
                response_disposition=response_disposition,
            )
        except Exception as exc:
            raise StorageError(
                "Failed to create GCS signed download URL",
                provider_key=self.provider_key,
                operation="create_signed_download",
                bucket=ref.bucket.value,
                object_key=ref.key,
                original_error=exc,
            ) from exc
        headers = {}
        if response_disposition:
            headers["content-disposition"] = response_disposition
        return SignedDownload(ref=ref, url=str(url), headers=headers, expires_at=expires_at)

    def public_url(self, ref: StorageObjectRef) -> str | None:
        if ref.bucket != StorageBucket.PUBLIC:
            return None
        if self.public_assets_base_url:
            return f"{self.public_assets_base_url}/{quote_object_key(ref.key)}"
        return (
            f"https://storage.googleapis.com/{self.public_bucket_name}/{quote_object_key(ref.key)}"
        )

    def require_valid_upload_signature(
        self,
        ref: StorageObjectRef,
        *,
        expires: int,
        signature: str,
        content_type: str,
    ) -> None:
        self._raise_no_local_signature("require_valid_upload_signature")

    def require_valid_download_signature(
        self,
        ref: StorageObjectRef,
        *,
        expires: int,
        signature: str,
        force_download: bool = False,
        filename: str = "",
    ) -> None:
        self._raise_no_local_signature("require_valid_download_signature")

    def _bucket(self, bucket: StorageBucket):
        return self.public_bucket if bucket == StorageBucket.PUBLIC else self.private_bucket

    def _create_client(self, *, project_id: str | None):
        if gcs_storage is None:
            raise StorageProviderUnavailableError(
                "GCS storage requires the google-cloud-storage extra",
                provider_key=self.provider_key,
                operation="create_client",
            )
        try:
            return gcs_storage.Client(project=project_id)
        except Exception as exc:
            raise StorageProviderUnavailableError(
                "Failed to initialize GCS storage client",
                provider_key=self.provider_key,
                operation="create_client",
                original_error=exc,
            ) from exc

    def _raise_no_local_signature(self, operation: str) -> None:
        raise StorageProviderUnavailableError(
            "GCS signed URLs are verified by Google Cloud Storage, not local callback routes",
            provider_key=self.provider_key,
            operation=operation,
        )


def _is_gcs_not_found(exc: Exception) -> bool:
    if gcs_exceptions is not None and isinstance(exc, gcs_exceptions.NotFound):
        return True
    return getattr(exc, "code", None) == 404
