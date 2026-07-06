# apps/api/services/storage/providers/s3.py

"""Amazon S3 provider for the storage contract."""

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
    import boto3
except ImportError:  # pragma: no cover - base install intentionally omits SDKs
    boto3 = None

try:  # pragma: no cover - exercised through provider-specific extras
    from botocore.exceptions import ClientError
except ImportError:  # pragma: no cover - base install intentionally omits SDKs
    ClientError = None


class S3StorageProvider:
    """S3 implementation of the provider-neutral contract."""

    provider_key = "s3"

    def __init__(
        self,
        *,
        public_bucket_name: str,
        private_bucket_name: str,
        region_name: str,
        public_assets_base_url: str,
        public_cache_control: str | None = None,
        access_key_id: str | None = None,
        secret_access_key: str | None = None,
        client: Any | None = None,
    ) -> None:
        self.public_bucket_name = _require_setting(
            public_bucket_name,
            "S3_PUBLIC_ASSETS_BUCKET",
            provider_key=self.provider_key,
        )
        self.private_bucket_name = _require_setting(
            private_bucket_name,
            "S3_PRIVATE_ASSETS_BUCKET",
            provider_key=self.provider_key,
        )
        self.region_name = _require_setting(
            region_name, "AWS_REGION", provider_key=self.provider_key
        )
        self.public_assets_base_url = _require_setting(
            public_assets_base_url,
            "PUBLIC_ASSETS_BASE_URL",
            provider_key=self.provider_key,
        ).rstrip("/")
        self.public_cache_control = public_cache_control
        self.client = (
            client
            if client is not None
            else self._create_client(
                access_key_id=access_key_id,
                secret_access_key=secret_access_key,
            )
        )

    @classmethod
    def from_settings(cls, settings: Settings) -> S3StorageProvider:
        return cls(
            public_bucket_name=settings.S3_PUBLIC_ASSETS_BUCKET,
            private_bucket_name=settings.S3_PRIVATE_ASSETS_BUCKET,
            region_name=settings.AWS_REGION,
            public_assets_base_url=settings.PUBLIC_ASSETS_BASE_URL or "",
            public_cache_control=settings.PUBLIC_ASSETS_CACHE_CONTROL,
            access_key_id=settings.AWS_ACCESS_KEY_ID,
            secret_access_key=settings.AWS_SECRET_ACCESS_KEY.get_secret_value(),
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
        resolved_cache_control = cache_control
        if ref.bucket == StorageBucket.PUBLIC and resolved_cache_control is None:
            resolved_cache_control = self.public_cache_control

        params: dict[str, Any] = {
            "Bucket": self._bucket_name(ref.bucket),
            "Key": ref.key,
            "Body": data,
        }
        if content_type:
            params["ContentType"] = content_type
        if resolved_cache_control:
            params["CacheControl"] = resolved_cache_control
        if metadata:
            params["Metadata"] = _string_metadata(metadata)

        try:
            await asyncio.to_thread(self.client.put_object, **params)
        except Exception as exc:
            raise StorageError(
                "Failed to upload S3 object",
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
        try:
            response = await asyncio.to_thread(
                self.client.get_object,
                Bucket=self._bucket_name(ref.bucket),
                Key=ref.key,
            )
            body = response["Body"]
            try:
                return await asyncio.to_thread(body.read)
            finally:
                close = getattr(body, "close", None)
                if callable(close):
                    close()
        except Exception as exc:
            if _is_not_found_error(exc):
                raise StorageNotFoundError(
                    "Storage object not found",
                    provider_key=self.provider_key,
                    operation="get_object",
                    bucket=ref.bucket.value,
                    object_key=ref.key,
                ) from exc
            raise StorageError(
                "Failed to download S3 object",
                provider_key=self.provider_key,
                operation="get_object",
                bucket=ref.bucket.value,
                object_key=ref.key,
                original_error=exc,
            ) from exc

    async def stat_object(self, ref: StorageObjectRef) -> StoredObject | None:
        try:
            response = await asyncio.to_thread(
                self.client.head_object,
                Bucket=self._bucket_name(ref.bucket),
                Key=ref.key,
            )
        except Exception as exc:
            if _is_not_found_error(exc):
                return None
            raise StorageError(
                "Failed to read S3 object metadata",
                provider_key=self.provider_key,
                operation="stat_object",
                bucket=ref.bucket.value,
                object_key=ref.key,
                original_error=exc,
            ) from exc

        etag = str(response.get("ETag") or "").strip('"')
        return StoredObject(
            ref=ref,
            size_bytes=int(response.get("ContentLength") or 0),
            etag=etag,
            content_type=response.get("ContentType"),
            cache_control=response.get("CacheControl"),
            metadata=_string_metadata(response.get("Metadata")),
            public_url=self.public_url(ref),
            updated_at=_as_aware_datetime(response.get("LastModified")),
        )

    async def delete_object(self, ref: StorageObjectRef) -> bool:
        if await self.stat_object(ref) is None:
            return False
        try:
            await asyncio.to_thread(
                self.client.delete_object,
                Bucket=self._bucket_name(ref.bucket),
                Key=ref.key,
            )
            return True
        except Exception as exc:
            raise StorageError(
                "Failed to delete S3 object",
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
        try:
            url = await asyncio.to_thread(
                self.client.generate_presigned_url,
                "put_object",
                Params={
                    "Bucket": self._bucket_name(ref.bucket),
                    "Key": ref.key,
                    "ContentType": normalized_content_type,
                },
                ExpiresIn=max(1, int(expires_in.total_seconds())),
                HttpMethod="PUT",
            )
        except Exception as exc:
            raise StorageError(
                "Failed to create S3 signed upload URL",
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

        params = {"Bucket": self._bucket_name(ref.bucket), "Key": ref.key}
        response_disposition = (
            build_content_disposition(filename or ref.key.rsplit("/", 1)[-1])
            if force_download
            else None
        )
        if response_disposition:
            params["ResponseContentDisposition"] = response_disposition

        try:
            url = await asyncio.to_thread(
                self.client.generate_presigned_url,
                "get_object",
                Params=params,
                ExpiresIn=max(1, int(expires_in.total_seconds())),
                HttpMethod="GET",
            )
        except Exception as exc:
            raise StorageError(
                "Failed to create S3 signed download URL",
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
        return f"{self.public_assets_base_url}/{quote_object_key(ref.key)}"

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

    def _bucket_name(self, bucket: StorageBucket) -> str:
        return (
            self.public_bucket_name if bucket == StorageBucket.PUBLIC else self.private_bucket_name
        )

    def _create_client(self, *, access_key_id: str | None, secret_access_key: str | None):
        if boto3 is None:
            raise StorageProviderUnavailableError(
                "S3 storage requires the boto3 extra",
                provider_key=self.provider_key,
                operation="create_client",
            )
        has_access_key = bool((access_key_id or "").strip())
        has_secret_key = bool((secret_access_key or "").strip())
        if has_access_key != has_secret_key:
            raise StorageProviderUnavailableError(
                "AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY must be configured together",
                provider_key=self.provider_key,
                operation="create_client",
            )

        kwargs: dict[str, Any] = {"region_name": self.region_name}
        if has_access_key and has_secret_key:
            kwargs["aws_access_key_id"] = access_key_id
            kwargs["aws_secret_access_key"] = secret_access_key
        try:
            return boto3.client("s3", **kwargs)
        except Exception as exc:
            raise StorageProviderUnavailableError(
                "Failed to initialize S3 storage client",
                provider_key=self.provider_key,
                operation="create_client",
                original_error=exc,
            ) from exc

    def _raise_no_local_signature(self, operation: str) -> None:
        raise StorageProviderUnavailableError(
            "S3 signed URLs are verified by S3, not local callback routes",
            provider_key=self.provider_key,
            operation=operation,
        )


def _is_not_found_error(exc: Exception) -> bool:
    if ClientError is not None and isinstance(exc, ClientError):
        code = exc.response.get("Error", {}).get("Code")
        return str(code) in {"404", "NoSuchKey", "NoSuchBucket", "NotFound"}
    response = getattr(exc, "response", None)
    if isinstance(response, dict):
        code = response.get("Error", {}).get("Code")
        return str(code) in {"404", "NoSuchKey", "NoSuchBucket", "NotFound"}
    return getattr(exc, "status_code", None) == 404
