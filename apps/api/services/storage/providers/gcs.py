# apps/api/services/storage/providers/gcs.py

"""Google Cloud Storage provider for the storage contract."""

from __future__ import annotations

import asyncio
import threading
from collections import OrderedDict
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any
from uuid import UUID

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
    StoragePreconditionError,
    StorageProviderUnavailableError,
    StorageValidationError,
)
from services.storage.paths import build_content_disposition, quote_object_key
from services.storage.provider import STORAGE_STREAM_CHUNK_SIZE
from services.storage.providers._common import (
    as_aware_datetime as _as_aware_datetime,
    require_content_type as _require_content_type,
    require_setting as _require_setting,
    string_metadata as _string_metadata,
)
from services.storage.workspace_buckets import workspace_bucket_name, workspace_id_for_ref

if TYPE_CHECKING:
    from core.settings import Settings

GCS_WORKSPACE_SOFT_DELETE_SECONDS = 30 * 24 * 60 * 60

try:  # pragma: no cover - exercised through provider-specific extras
    from google.cloud import storage as gcs_storage
except ImportError:  # pragma: no cover - base install intentionally omits SDKs
    gcs_storage = None

try:  # pragma: no cover - exercised through provider-specific extras
    from google.api_core import exceptions as gcs_exceptions
except ImportError:  # pragma: no cover - base install intentionally omits SDKs
    gcs_exceptions = None

try:  # pragma: no cover - exercised through provider-specific extras
    from google.auth import credentials as google_auth_credentials
    from google.auth.transport.requests import Request as GoogleAuthRequest
except ImportError:  # pragma: no cover - base install intentionally omits SDKs
    google_auth_credentials = None
    GoogleAuthRequest = None


class GcsStorageProvider:
    """Google Cloud Storage implementation of the provider-neutral contract."""

    provider_key = "gcs"

    def __init__(
        self,
        *,
        public_bucket_name: str,
        workspace_bucket_prefix: str,
        workspace_bucket_location: str,
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
        self.workspace_bucket_prefix = _require_setting(
            workspace_bucket_prefix,
            "WORKSPACE_BUCKET_PREFIX",
            provider_key=self.provider_key,
        )
        self.public_assets_base_url = (
            public_assets_base_url.rstrip("/") if public_assets_base_url else None
        )
        self.public_cache_control = public_cache_control
        self.project_id = _require_setting(
            project_id,
            "GCP_PROJECT_ID",
            provider_key=self.provider_key,
        )
        self.workspace_bucket_location = _require_setting(
            workspace_bucket_location,
            "GCS_WORKSPACE_BUCKET_LOCATION",
            provider_key=self.provider_key,
        )
        self.client = client if client is not None else self._create_client(project_id=project_id)
        self.public_bucket = self.client.bucket(self.public_bucket_name)
        self._workspace_buckets: OrderedDict[UUID, Any] = OrderedDict()
        self._ensured_workspace_ids: set[UUID] = set()
        self._workspace_buckets_lock = threading.Lock()
        self._signing_credentials_lock = threading.Lock()

    @classmethod
    def from_settings(cls, settings: Settings) -> GcsStorageProvider:
        return cls(
            public_bucket_name=settings.GCS_PUBLIC_ASSETS_BUCKET,
            workspace_bucket_prefix=settings.WORKSPACE_BUCKET_PREFIX,
            public_assets_base_url=settings.PUBLIC_ASSETS_BASE_URL,
            public_cache_control=settings.PUBLIC_ASSETS_CACHE_CONTROL,
            project_id=settings.GCP_PROJECT_ID,
            workspace_bucket_location=settings.GCS_WORKSPACE_BUCKET_LOCATION,
        )

    async def ensure_workspace_bucket(self, workspace_id: UUID) -> None:
        """Create and harden the GCS bucket dedicated to one workspace."""
        with self._workspace_buckets_lock:
            if workspace_id in self._ensured_workspace_ids:
                self._workspace_buckets.move_to_end(workspace_id)
                return
        bucket = self._workspace_bucket(workspace_id)
        try:
            await asyncio.to_thread(bucket.reload)
        except Exception as exc:
            if not _is_gcs_not_found(exc):
                raise StorageError(
                    "Failed to inspect workspace GCS bucket",
                    provider_key=self.provider_key,
                    operation="ensure_workspace_bucket",
                    bucket=bucket.name,
                    original_error=exc,
                ) from exc
            try:
                bucket = await asyncio.to_thread(
                    self.client.create_bucket,
                    bucket,
                    project=self.project_id,
                    location=self.workspace_bucket_location,
                )
            except Exception as create_exc:
                if not _is_gcs_conflict(create_exc):
                    raise StorageError(
                        "Failed to create workspace GCS bucket",
                        provider_key=self.provider_key,
                        operation="ensure_workspace_bucket",
                        bucket=bucket.name,
                        original_error=create_exc,
                    ) from create_exc
                await asyncio.to_thread(bucket.reload)

        try:
            bucket.iam_configuration.uniform_bucket_level_access_enabled = True
            bucket.iam_configuration.public_access_prevention = "enforced"
            bucket.versioning_enabled = True
            bucket.soft_delete_policy.retention_duration_seconds = GCS_WORKSPACE_SOFT_DELETE_SECONDS
            bucket.labels = {**(bucket.labels or {}), "praxis-workspace": str(workspace_id)}
            await asyncio.to_thread(bucket.patch)
        except Exception as exc:
            raise StorageError(
                "Failed to harden workspace GCS bucket",
                provider_key=self.provider_key,
                operation="ensure_workspace_bucket",
                bucket=bucket.name,
                original_error=exc,
            ) from exc
        self._remember_ensured_workspace_bucket(workspace_id, bucket)

    async def put_object(
        self,
        ref: StorageObjectRef,
        data: bytes,
        *,
        content_type: str | None = None,
        cache_control: str | None = None,
        metadata: dict[str, str] | None = None,
        overwrite: bool = True,
    ) -> StoredObject:
        workspace_id = workspace_id_for_ref(ref)
        if workspace_id is not None:
            await self.ensure_workspace_bucket(workspace_id)
        bucket = self._bucket(ref)
        blob = bucket.blob(ref.key)
        resolved_cache_control = cache_control
        if ref.bucket == StorageBucket.PUBLIC and resolved_cache_control is None:
            resolved_cache_control = self.public_cache_control
        blob.cache_control = resolved_cache_control
        blob.metadata = _string_metadata(metadata)

        try:
            upload_kwargs: dict[str, Any] = {"content_type": content_type}
            if not overwrite:
                upload_kwargs["if_generation_match"] = 0
            await asyncio.to_thread(blob.upload_from_string, data, **upload_kwargs)
        except Exception as exc:
            if _is_gcs_precondition_failed(exc):
                raise StoragePreconditionError(
                    "Storage object already exists",
                    provider_key=self.provider_key,
                    operation="put_object",
                    bucket=ref.bucket.value,
                    object_key=ref.key,
                    original_error=exc,
                ) from exc
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
        blob = self._bucket(ref).blob(ref.key)
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

    async def stream_object(self, ref: StorageObjectRef):
        blob = self._bucket(ref).blob(ref.key)
        try:
            exists = await asyncio.to_thread(blob.exists)
            if not exists:
                raise StorageNotFoundError(
                    "Storage object not found",
                    provider_key=self.provider_key,
                    operation="stream_object",
                    bucket=ref.bucket.value,
                    object_key=ref.key,
                )
            open_blob = getattr(blob, "open", None)
            if not callable(open_blob):
                yield await self.get_object(ref)
                return

            stream = await asyncio.to_thread(open_blob, "rb")
            try:
                while True:
                    chunk = await asyncio.to_thread(stream.read, STORAGE_STREAM_CHUNK_SIZE)
                    if not chunk:
                        break
                    yield chunk
            finally:
                await asyncio.to_thread(stream.close)
        except StorageNotFoundError:
            raise
        except Exception as exc:
            raise StorageError(
                "Failed to stream GCS object",
                provider_key=self.provider_key,
                operation="stream_object",
                bucket=ref.bucket.value,
                object_key=ref.key,
                original_error=exc,
            ) from exc

    async def stat_object(self, ref: StorageObjectRef) -> StoredObject | None:
        blob = self._bucket(ref).blob(ref.key)
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
        blob = self._bucket(ref).blob(ref.key)
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

    async def promote_object(
        self,
        source: StorageObjectRef,
        destination: StorageObjectRef,
        *,
        expected_source_etag: str,
    ) -> StoredObject:
        if source.bucket != destination.bucket or source == destination:
            raise StorageValidationError(
                "Storage promotion requires distinct objects in the same bucket",
                provider_key=self.provider_key,
                operation="promote_object",
                bucket=destination.bucket.value,
                object_key=destination.key,
            )

        source_workspace_id = workspace_id_for_ref(source)
        destination_workspace_id = workspace_id_for_ref(destination)
        if source_workspace_id != destination_workspace_id:
            raise StorageValidationError(
                "Storage promotion cannot cross workspace buckets",
                provider_key=self.provider_key,
                operation="promote_object",
                bucket=destination.bucket.value,
                object_key=destination.key,
            )
        if destination_workspace_id is not None:
            await self.ensure_workspace_bucket(destination_workspace_id)
        bucket = self._bucket(source)
        source_blob = bucket.blob(source.key)
        try:
            await asyncio.to_thread(source_blob.reload)
            if str(source_blob.etag or "") != expected_source_etag:
                raise StoragePreconditionError(
                    "Storage promotion source changed after validation",
                    provider_key=self.provider_key,
                    operation="promote_object",
                    bucket=source.bucket.value,
                    object_key=source.key,
                )
            source_generation = int(source_blob.generation)
            await asyncio.to_thread(
                bucket.copy_blob,
                source_blob,
                bucket,
                new_name=destination.key,
                source_generation=source_generation,
                if_source_generation_match=source_generation,
                if_generation_match=0,
            )
        except StoragePreconditionError:
            raise
        except Exception as exc:
            if _is_gcs_precondition_failed(exc):
                raise StoragePreconditionError(
                    "Storage promotion precondition failed",
                    provider_key=self.provider_key,
                    operation="promote_object",
                    bucket=destination.bucket.value,
                    object_key=destination.key,
                    original_error=exc,
                ) from exc
            if _is_gcs_not_found(exc):
                raise StorageNotFoundError(
                    "Storage promotion source was not found",
                    provider_key=self.provider_key,
                    operation="promote_object",
                    bucket=source.bucket.value,
                    object_key=source.key,
                    original_error=exc,
                ) from exc
            raise StorageError(
                "Failed to promote GCS object",
                provider_key=self.provider_key,
                operation="promote_object",
                bucket=destination.bucket.value,
                object_key=destination.key,
                original_error=exc,
            ) from exc

        stored = await self.stat_object(destination)
        if stored is None:
            raise StorageNotFoundError(
                "Promoted object could not be read after copy",
                provider_key=self.provider_key,
                operation="promote_object",
                bucket=destination.bucket.value,
                object_key=destination.key,
            )
        return stored

    async def create_signed_upload(
        self,
        ref: StorageObjectRef,
        *,
        content_type: str,
        expires_in: timedelta,
    ) -> SignedUpload:
        workspace_id = workspace_id_for_ref(ref)
        if workspace_id is not None:
            await self.ensure_workspace_bucket(workspace_id)
        normalized_content_type = _require_content_type(
            content_type, provider_key=self.provider_key, ref=ref
        )
        expires_at = datetime.now(UTC) + expires_in
        blob = self._bucket(ref).blob(ref.key)
        upload_headers = {
            "content-type": normalized_content_type,
            "x-goog-if-generation-match": "0",
        }
        try:
            signing_kwargs = await asyncio.to_thread(self._remote_signing_kwargs)
            url = await asyncio.to_thread(
                blob.generate_signed_url,
                expiration=expires_at,
                method="PUT",
                content_type=normalized_content_type,
                version="v4",
                headers={"x-goog-if-generation-match": "0"},
                **signing_kwargs,
            )
        except StorageError:
            raise
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
            headers=upload_headers,
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
        blob = self._bucket(ref).blob(ref.key)
        try:
            signing_kwargs = await asyncio.to_thread(self._remote_signing_kwargs)
            url = await asyncio.to_thread(
                blob.generate_signed_url,
                expiration=expires_at,
                method="GET",
                version="v4",
                response_disposition=response_disposition,
                **signing_kwargs,
            )
        except StorageError:
            raise
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

    def _bucket(self, ref: StorageObjectRef):
        workspace_id = workspace_id_for_ref(ref)
        return self.public_bucket if workspace_id is None else self._workspace_bucket(workspace_id)

    def _workspace_bucket(self, workspace_id: UUID):
        with self._workspace_buckets_lock:
            cached = self._workspace_buckets.get(workspace_id)
            if cached is not None:
                self._workspace_buckets.move_to_end(workspace_id)
                return cached
            bucket = self.client.bucket(
                workspace_bucket_name(self.workspace_bucket_prefix, workspace_id)
            )
            self._cache_workspace_bucket_locked(workspace_id, bucket, ensured=False)
            return bucket

    def _remember_ensured_workspace_bucket(self, workspace_id: UUID, bucket: Any) -> None:
        with self._workspace_buckets_lock:
            self._cache_workspace_bucket_locked(workspace_id, bucket, ensured=True)

    def _cache_workspace_bucket_locked(
        self,
        workspace_id: UUID,
        bucket: Any,
        *,
        ensured: bool,
    ) -> None:
        self._workspace_buckets[workspace_id] = bucket
        self._workspace_buckets.move_to_end(workspace_id)
        if ensured:
            self._ensured_workspace_ids.add(workspace_id)
        if len(self._workspace_buckets) > 256:
            evicted_workspace_id, _handle = self._workspace_buckets.popitem(last=False)
            self._ensured_workspace_ids.discard(evicted_workspace_id)

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

    def _remote_signing_kwargs(self) -> dict[str, str]:
        """Return IAM signing inputs when ADC cannot sign with a private key locally."""
        credentials = getattr(self.client, "_credentials", None)
        if credentials is None or google_auth_credentials is None:
            return {}
        if isinstance(credentials, google_auth_credentials.Signing):
            return {}
        if GoogleAuthRequest is None:
            raise StorageProviderUnavailableError(
                "GCS remote signed URLs require google-auth request support",
                provider_key=self.provider_key,
                operation="sign_url",
            )

        with self._signing_credentials_lock:
            service_account_email = getattr(credentials, "service_account_email", None)
            if (
                not getattr(credentials, "valid", False)
                or not service_account_email
                or service_account_email == "default"
            ):
                try:
                    credentials.refresh(GoogleAuthRequest())
                except Exception as exc:
                    raise StorageProviderUnavailableError(
                        "Failed to refresh GCS credentials for remote URL signing",
                        provider_key=self.provider_key,
                        operation="sign_url",
                        original_error=exc,
                    ) from exc
                service_account_email = getattr(credentials, "service_account_email", None)

            access_token = getattr(credentials, "token", None)
            if not service_account_email or service_account_email == "default" or not access_token:
                raise StorageProviderUnavailableError(
                    "GCS signed URLs require signing credentials or service-account ADC",
                    provider_key=self.provider_key,
                    operation="sign_url",
                )
            return {
                "service_account_email": str(service_account_email),
                "access_token": str(access_token),
            }

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


def _is_gcs_precondition_failed(exc: Exception) -> bool:
    return getattr(exc, "code", None) in {409, 412}


def _is_gcs_conflict(exc: Exception) -> bool:
    return getattr(exc, "code", None) == 409
