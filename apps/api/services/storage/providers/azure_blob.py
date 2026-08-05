# apps/api/services/storage/providers/azure_blob.py

"""Azure Blob Storage provider for the storage contract."""

from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import threading
from collections import OrderedDict
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any
from urllib.parse import urlencode
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
    StorageSignatureError,
    StorageValidationError,
)
from services.storage.paths import build_content_disposition, quote_object_key
from services.storage.providers._common import (
    as_aware_datetime as _as_aware_datetime,
    require_content_type as _require_content_type,
    require_setting as _require_setting,
    string_metadata as _string_metadata,
)
from services.storage.workspace_buckets import workspace_bucket_name, workspace_id_for_ref

if TYPE_CHECKING:
    from core.settings import Settings

try:  # pragma: no cover - exercised through provider-specific extras
    from azure.identity import DefaultAzureCredential
except ImportError:  # pragma: no cover - base install intentionally omits SDKs
    DefaultAzureCredential = None

try:  # pragma: no cover - exercised through provider-specific extras
    from azure.core import MatchConditions
    from azure.core.exceptions import ResourceNotFoundError
except ImportError:  # pragma: no cover - base install intentionally omits SDKs
    MatchConditions = None
    ResourceNotFoundError = None

try:  # pragma: no cover - exercised through provider-specific extras
    from azure.storage.blob import (
        BlobSasPermissions,
        BlobServiceClient,
        ContentSettings,
        generate_blob_sas,
    )
except ImportError:  # pragma: no cover - base install intentionally omits SDKs
    BlobSasPermissions = None
    BlobServiceClient = None
    ContentSettings = None
    generate_blob_sas = None

SIGNED_URL_CLOCK_SKEW_MINUTES = 5
DELEGATION_KEY_CACHE_LIFETIME_HOURS = 6
DELEGATION_KEY_REFRESH_BUFFER_MINUTES = 10


class AzureBlobStorageProvider:
    """Azure Blob implementation of the provider-neutral contract."""

    provider_key = "azure_blob"

    def __init__(
        self,
        *,
        account_name: str,
        public_container_name: str,
        workspace_bucket_prefix: str,
        app_base_url: str,
        api_prefix: str,
        secret_key: str,
        account_url: str | None = None,
        managed_identity_client_id: str | None = None,
        public_assets_base_url: str | None = None,
        public_cache_control: str | None = None,
        credential: Any | None = None,
        service_client: Any | None = None,
        content_settings_cls: Any | None = None,
        match_conditions_cls: Any | None = None,
        sas_permissions_cls: Any | None = None,
        generate_sas_func: Any | None = None,
    ) -> None:
        self.account_name = _require_setting(
            account_name,
            "AZURE_STORAGE_ACCOUNT_NAME",
            provider_key=self.provider_key,
        )
        self.public_container_name = _require_setting(
            public_container_name,
            "AZURE_STORAGE_PUBLIC_CONTAINER",
            provider_key=self.provider_key,
        )
        self.workspace_bucket_prefix = _require_setting(
            workspace_bucket_prefix,
            "WORKSPACE_BUCKET_PREFIX",
            provider_key=self.provider_key,
        )
        self.app_base_url = app_base_url.rstrip("/")
        self.api_prefix = api_prefix.rstrip("/")
        self.secret_key = secret_key
        self.account_url = (
            account_url or f"https://{self.account_name}.blob.core.windows.net"
        ).rstrip("/")
        self.managed_identity_client_id = (managed_identity_client_id or "").strip()
        self.public_assets_base_url = (
            public_assets_base_url.rstrip("/") if public_assets_base_url else None
        )
        self.public_cache_control = public_cache_control
        self.credential = credential if credential is not None else self._create_credential()
        self.service_client = (
            service_client if service_client is not None else self._create_service_client()
        )
        self.public_container = self.service_client.get_container_client(self.public_container_name)
        self._workspace_containers: OrderedDict[UUID, Any] = OrderedDict()
        self._ensured_workspace_ids: set[UUID] = set()
        self._workspace_containers_lock = threading.Lock()
        self.content_settings_cls = content_settings_cls or self._require_content_settings_cls()
        self.match_conditions_cls = match_conditions_cls or self._require_match_conditions_cls()
        self.sas_permissions_cls = sas_permissions_cls or self._require_sas_permissions_cls()
        self.generate_sas_func = generate_sas_func or self._require_generate_sas_func()
        self._delegation_key_lock = threading.Lock()
        self._cached_delegation_key = None
        self._cached_delegation_expires_on: datetime | None = None

    @classmethod
    def from_settings(cls, settings: Settings) -> AzureBlobStorageProvider:
        return cls(
            account_name=settings.AZURE_STORAGE_ACCOUNT_NAME,
            public_container_name=settings.AZURE_STORAGE_PUBLIC_CONTAINER,
            workspace_bucket_prefix=settings.WORKSPACE_BUCKET_PREFIX,
            app_base_url=settings.APP_BASE_URL,
            api_prefix=settings.API_V1_PREFIX,
            secret_key=settings.SECRET_KEY.get_secret_value(),
            account_url=settings.AZURE_STORAGE_ACCOUNT_URL,
            managed_identity_client_id=settings.AZURE_MANAGED_IDENTITY_CLIENT_ID,
            public_assets_base_url=settings.PUBLIC_ASSETS_BASE_URL,
            public_cache_control=settings.PUBLIC_ASSETS_CACHE_CONTROL,
        )

    async def ensure_workspace_bucket(self, workspace_id: UUID) -> None:
        """Create and keep private the Azure container dedicated to one workspace."""
        with self._workspace_containers_lock:
            if workspace_id in self._ensured_workspace_ids:
                self._workspace_containers.move_to_end(workspace_id)
                return
        container = self._workspace_container(workspace_id)
        metadata = {"praxis_workspace": str(workspace_id)}
        try:
            properties = await asyncio.to_thread(container.get_container_properties)
        except Exception as exc:
            if not _is_azure_not_found(exc):
                raise StorageError(
                    "Failed to inspect workspace Azure container",
                    provider_key=self.provider_key,
                    operation="ensure_workspace_bucket",
                    bucket=container.container_name,
                    original_error=exc,
                ) from exc
            try:
                await asyncio.to_thread(container.create_container, metadata=metadata)
            except Exception as create_exc:
                if not _is_azure_precondition_failed(create_exc):
                    raise StorageError(
                        "Failed to create workspace Azure container",
                        provider_key=self.provider_key,
                        operation="ensure_workspace_bucket",
                        bucket=container.container_name,
                        original_error=create_exc,
                    ) from create_exc
                properties = await asyncio.to_thread(container.get_container_properties)
            else:
                properties = None

        try:
            existing_metadata = _string_metadata(
                _get_property(properties, "metadata") if properties is not None else None
            )
            existing_signed_identifiers = {}
            if properties is not None:
                access_policy = await asyncio.to_thread(container.get_container_access_policy)
                existing_signed_identifiers = (
                    _get_property(access_policy, "signed_identifiers") or {}
                )
            await asyncio.to_thread(
                container.set_container_metadata,
                metadata={**existing_metadata, **metadata},
            )
            await asyncio.to_thread(
                container.set_container_access_policy,
                signed_identifiers=existing_signed_identifiers,
                public_access=None,
            )
        except Exception as exc:
            raise StorageError(
                "Failed to harden workspace Azure container",
                provider_key=self.provider_key,
                operation="ensure_workspace_bucket",
                bucket=container.container_name,
                original_error=exc,
            ) from exc
        self._remember_ensured_workspace_container(workspace_id, container)

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
        resolved_cache_control = cache_control
        if ref.bucket == StorageBucket.PUBLIC and resolved_cache_control is None:
            resolved_cache_control = self.public_cache_control
        content_settings = self.content_settings_cls(
            content_type=content_type,
            cache_control=resolved_cache_control,
        )
        blob = self._container(ref).get_blob_client(ref.key)
        try:
            await asyncio.to_thread(
                blob.upload_blob,
                data,
                overwrite=overwrite,
                content_settings=content_settings,
                metadata=_string_metadata(metadata) or None,
            )
        except Exception as exc:
            if _is_azure_precondition_failed(exc):
                raise StoragePreconditionError(
                    "Storage object already exists",
                    provider_key=self.provider_key,
                    operation="put_object",
                    bucket=ref.bucket.value,
                    object_key=ref.key,
                    original_error=exc,
                ) from exc
            raise StorageError(
                "Failed to upload Azure Blob object",
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
        blob = self._container(ref).get_blob_client(ref.key)
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
            return await asyncio.to_thread(lambda: blob.download_blob().readall())
        except StorageNotFoundError:
            raise
        except Exception as exc:
            raise StorageError(
                "Failed to download Azure Blob object",
                provider_key=self.provider_key,
                operation="get_object",
                bucket=ref.bucket.value,
                object_key=ref.key,
                original_error=exc,
            ) from exc

    async def stream_object(self, ref: StorageObjectRef):
        blob = self._container(ref).get_blob_client(ref.key)
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
            download = await asyncio.to_thread(blob.download_blob)
            chunks = getattr(download, "chunks", None)
            if not callable(chunks):
                yield await asyncio.to_thread(download.readall)
                return

            iterator = chunks()
            while True:
                chunk = await asyncio.to_thread(_next_or_none, iterator)
                if chunk is None:
                    break
                if chunk:
                    yield chunk
        except StorageNotFoundError:
            raise
        except Exception as exc:
            raise StorageError(
                "Failed to stream Azure Blob object",
                provider_key=self.provider_key,
                operation="stream_object",
                bucket=ref.bucket.value,
                object_key=ref.key,
                original_error=exc,
            ) from exc

    async def stat_object(self, ref: StorageObjectRef) -> StoredObject | None:
        blob = self._container(ref).get_blob_client(ref.key)
        try:
            properties = await asyncio.to_thread(blob.get_blob_properties)
        except Exception as exc:
            if _is_azure_not_found(exc):
                return None
            raise StorageError(
                "Failed to read Azure Blob object metadata",
                provider_key=self.provider_key,
                operation="stat_object",
                bucket=ref.bucket.value,
                object_key=ref.key,
                original_error=exc,
            ) from exc

        content_settings = getattr(properties, "content_settings", None)
        return StoredObject(
            ref=ref,
            size_bytes=int(_get_property(properties, "size", "content_length") or 0),
            etag=str(_get_property(properties, "etag") or ""),
            content_type=getattr(content_settings, "content_type", None),
            cache_control=getattr(content_settings, "cache_control", None),
            metadata=_string_metadata(_get_property(properties, "metadata")),
            public_url=self.public_url(ref),
            updated_at=_as_aware_datetime(_get_property(properties, "last_modified")),
        )

    async def delete_object(self, ref: StorageObjectRef) -> bool:
        blob = self._container(ref).get_blob_client(ref.key)
        try:
            exists = await asyncio.to_thread(blob.exists)
            if not exists:
                return False
            await asyncio.to_thread(blob.delete_blob, delete_snapshots="include")
            return True
        except Exception as exc:
            raise StorageError(
                "Failed to delete Azure Blob object",
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
        container = self._container(source)
        source_blob = container.get_blob_client(source.key)
        destination_blob = container.get_blob_client(destination.key)
        try:
            properties = await asyncio.to_thread(source_blob.get_blob_properties)
            if str(_get_property(properties, "etag") or "") != expected_source_etag:
                raise StoragePreconditionError(
                    "Storage promotion source changed after validation",
                    provider_key=self.provider_key,
                    operation="promote_object",
                    bucket=source.bucket.value,
                    object_key=source.key,
                )
            download = await asyncio.to_thread(
                source_blob.download_blob,
                etag=expected_source_etag,
                match_condition=self.match_conditions_cls.IfNotModified,
            )
            data = await asyncio.to_thread(download.readall)
            await asyncio.to_thread(
                destination_blob.upload_blob,
                data,
                overwrite=False,
                content_settings=_get_property(properties, "content_settings"),
                metadata=_string_metadata(_get_property(properties, "metadata")) or None,
            )
        except StoragePreconditionError:
            raise
        except Exception as exc:
            if _is_azure_precondition_failed(exc):
                raise StoragePreconditionError(
                    "Storage promotion precondition failed",
                    provider_key=self.provider_key,
                    operation="promote_object",
                    bucket=destination.bucket.value,
                    object_key=destination.key,
                    original_error=exc,
                ) from exc
            if _is_azure_not_found(exc):
                raise StorageNotFoundError(
                    "Storage promotion source was not found",
                    provider_key=self.provider_key,
                    operation="promote_object",
                    bucket=source.bucket.value,
                    object_key=source.key,
                    original_error=exc,
                ) from exc
            raise StorageError(
                "Failed to promote Azure Blob object",
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
        expected_size_bytes: int,
        expires_in: timedelta,
    ) -> SignedUpload:
        workspace_id = workspace_id_for_ref(ref)
        if workspace_id is not None:
            await self.ensure_workspace_bucket(workspace_id)
        normalized_content_type = _require_content_type(
            content_type, provider_key=self.provider_key, ref=ref
        )
        expires_at = datetime.now(UTC) + expires_in
        expires = int(expires_at.timestamp())
        query = {
            "content_type": normalized_content_type,
            "expires": str(expires),
            "size_bytes": str(expected_size_bytes),
            "sig": self._upload_signature(
                ref=ref,
                expires=expires,
                content_type=normalized_content_type,
                expected_size_bytes=expected_size_bytes,
            ),
        }
        url = (
            f"{self.app_base_url}{self.api_prefix}/storage/upload/"
            f"{ref.bucket.value}/{quote_object_key(ref.key)}?{urlencode(query)}"
        )
        return SignedUpload(
            ref=ref,
            url=url,
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

        content_disposition = (
            build_content_disposition(filename or ref.key.rsplit("/", 1)[-1])
            if force_download
            else None
        )
        url = await self._create_signed_blob_url(
            ref=ref,
            expires_at=expires_at,
            permission_kwargs={"read": True},
            content_disposition=content_disposition,
        )
        headers = {}
        if content_disposition:
            headers["content-disposition"] = content_disposition
        return SignedDownload(ref=ref, url=url, headers=headers, expires_at=expires_at)

    def public_url(self, ref: StorageObjectRef) -> str | None:
        if ref.bucket != StorageBucket.PUBLIC:
            return None
        base = self.public_assets_base_url or f"{self.account_url}/{self.public_container_name}"
        return f"{base}/{quote_object_key(ref.key)}"

    def require_valid_upload_signature(
        self,
        ref: StorageObjectRef,
        *,
        expires: int,
        signature: str,
        content_type: str,
        expected_size_bytes: int,
    ) -> None:
        if expires < int(datetime.now(UTC).timestamp()) or not hmac.compare_digest(
            signature,
            self._upload_signature(
                ref=ref,
                expires=expires,
                content_type=content_type,
                expected_size_bytes=expected_size_bytes,
            ),
        ):
            raise StorageSignatureError(
                "Invalid or expired Azure upload URL",
                provider_key=self.provider_key,
                operation="upload",
                bucket=ref.bucket.value,
                object_key=ref.key,
            )

    def _upload_signature(
        self,
        *,
        ref: StorageObjectRef,
        expires: int,
        content_type: str,
        expected_size_bytes: int,
    ) -> str:
        payload = "\n".join(
            [
                "upload",
                ref.bucket.value,
                ref.key,
                str(expires),
                content_type,
                str(expected_size_bytes),
            ]
        )
        digest = hmac.new(self.secret_key.encode(), payload.encode(), hashlib.sha256).digest()
        return base64.urlsafe_b64encode(digest).decode().rstrip("=")

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

    def _container(self, ref: StorageObjectRef):
        workspace_id = workspace_id_for_ref(ref)
        return (
            self.public_container
            if workspace_id is None
            else self._workspace_container(workspace_id)
        )

    def _container_name(self, ref: StorageObjectRef) -> str:
        workspace_id = workspace_id_for_ref(ref)
        if workspace_id is None:
            return self.public_container_name
        return workspace_bucket_name(self.workspace_bucket_prefix, workspace_id)

    def _workspace_container(self, workspace_id: UUID):
        with self._workspace_containers_lock:
            cached = self._workspace_containers.get(workspace_id)
            if cached is not None:
                self._workspace_containers.move_to_end(workspace_id)
                return cached
            container = self.service_client.get_container_client(
                workspace_bucket_name(self.workspace_bucket_prefix, workspace_id)
            )
            self._cache_workspace_container_locked(workspace_id, container, ensured=False)
            return container

    def _remember_ensured_workspace_container(self, workspace_id: UUID, container: Any) -> None:
        with self._workspace_containers_lock:
            self._cache_workspace_container_locked(workspace_id, container, ensured=True)

    def _cache_workspace_container_locked(
        self,
        workspace_id: UUID,
        container: Any,
        *,
        ensured: bool,
    ) -> None:
        self._workspace_containers[workspace_id] = container
        self._workspace_containers.move_to_end(workspace_id)
        if ensured:
            self._ensured_workspace_ids.add(workspace_id)
        if len(self._workspace_containers) > 256:
            evicted_workspace_id, _handle = self._workspace_containers.popitem(last=False)
            self._ensured_workspace_ids.discard(evicted_workspace_id)

    async def _create_signed_blob_url(
        self,
        *,
        ref: StorageObjectRef,
        expires_at: datetime,
        permission_kwargs: dict[str, bool],
        content_disposition: str | None = None,
        content_type: str | None = None,
    ) -> str:
        starts_on = datetime.now(UTC) - timedelta(minutes=SIGNED_URL_CLOCK_SKEW_MINUTES)
        delegation_key = await self._get_user_delegation_key(expires_at=expires_at)
        permissions = self.sas_permissions_cls(**permission_kwargs)
        container_name = self._container_name(ref)
        try:
            sas_token = await asyncio.to_thread(
                self.generate_sas_func,
                account_name=self.account_name,
                container_name=container_name,
                blob_name=ref.key,
                user_delegation_key=delegation_key,
                permission=permissions,
                start=starts_on,
                expiry=expires_at,
                content_disposition=content_disposition,
                content_type=content_type,
            )
        except Exception as exc:
            raise StorageError(
                "Failed to create Azure Blob SAS URL",
                provider_key=self.provider_key,
                operation="generate_blob_sas",
                bucket=ref.bucket.value,
                object_key=ref.key,
                original_error=exc,
            ) from exc
        return f"{self.account_url}/{container_name}/{quote_object_key(ref.key)}?{sas_token}"

    async def _get_user_delegation_key(self, *, expires_at: datetime):
        with self._delegation_key_lock:
            if (
                self._cached_delegation_key is not None
                and self._cached_delegation_expires_on
                and self._cached_delegation_expires_on
                > expires_at + timedelta(minutes=DELEGATION_KEY_REFRESH_BUFFER_MINUTES)
            ):
                return self._cached_delegation_key

        starts_on = datetime.now(UTC) - timedelta(minutes=SIGNED_URL_CLOCK_SKEW_MINUTES)
        delegation_expires_on = starts_on + timedelta(hours=DELEGATION_KEY_CACHE_LIFETIME_HOURS)
        try:
            delegation_key = await asyncio.to_thread(
                self.service_client.get_user_delegation_key,
                starts_on,
                delegation_expires_on,
            )
        except Exception as exc:
            raise StorageError(
                "Failed to acquire Azure Blob user delegation key for signed URL generation",
                provider_key=self.provider_key,
                operation="get_user_delegation_key",
                original_error=exc,
            ) from exc

        with self._delegation_key_lock:
            self._cached_delegation_key = delegation_key
            self._cached_delegation_expires_on = delegation_expires_on
        return delegation_key

    def _create_credential(self):
        if DefaultAzureCredential is None:
            raise StorageProviderUnavailableError(
                "Azure Blob storage requires the azure extra",
                provider_key=self.provider_key,
                operation="create_credential",
            )
        kwargs = {}
        if self.managed_identity_client_id:
            kwargs["managed_identity_client_id"] = self.managed_identity_client_id
        try:
            return DefaultAzureCredential(**kwargs)
        except Exception as exc:
            raise StorageProviderUnavailableError(
                "Failed to initialize Azure Blob credential",
                provider_key=self.provider_key,
                operation="create_credential",
                original_error=exc,
            ) from exc

    def _create_service_client(self):
        if BlobServiceClient is None:
            raise StorageProviderUnavailableError(
                "Azure Blob storage requires the azure extra",
                provider_key=self.provider_key,
                operation="create_service_client",
            )
        try:
            return BlobServiceClient(account_url=self.account_url, credential=self.credential)
        except Exception as exc:
            raise StorageProviderUnavailableError(
                "Failed to initialize Azure Blob service client",
                provider_key=self.provider_key,
                operation="create_service_client",
                original_error=exc,
            ) from exc

    def _require_content_settings_cls(self):
        if ContentSettings is None:
            raise StorageProviderUnavailableError(
                "Azure Blob storage requires azure-storage-blob",
                provider_key=self.provider_key,
                operation="content_settings",
            )
        return ContentSettings

    def _require_match_conditions_cls(self):
        if MatchConditions is None:
            raise StorageProviderUnavailableError(
                "Azure Blob storage requires azure-core",
                provider_key=self.provider_key,
                operation="match_conditions",
            )
        return MatchConditions

    def _require_sas_permissions_cls(self):
        if BlobSasPermissions is None:
            raise StorageProviderUnavailableError(
                "Azure Blob storage requires azure-storage-blob",
                provider_key=self.provider_key,
                operation="sas_permissions",
            )
        return BlobSasPermissions

    def _require_generate_sas_func(self):
        if generate_blob_sas is None:
            raise StorageProviderUnavailableError(
                "Azure Blob storage requires azure-storage-blob",
                provider_key=self.provider_key,
                operation="generate_blob_sas",
            )
        return generate_blob_sas

    def _raise_no_local_signature(self, operation: str) -> None:
        raise StorageProviderUnavailableError(
            "Azure Blob SAS URLs are verified by Azure Storage, not local callback routes",
            provider_key=self.provider_key,
            operation=operation,
        )


def _is_azure_not_found(exc: Exception) -> bool:
    if ResourceNotFoundError is not None and isinstance(exc, ResourceNotFoundError):
        return True
    if getattr(exc, "status_code", None) == 404:
        return True
    return getattr(exc, "error_code", None) in {"BlobNotFound", "ResourceNotFound"}


def _is_azure_precondition_failed(exc: Exception) -> bool:
    return getattr(exc, "status_code", None) in {409, 412} or getattr(exc, "error_code", None) in {
        "BlobAlreadyExists",
        "ConditionNotMet",
        "ResourceAlreadyExists",
    }


def _get_property(value: Any, *names: str) -> Any:
    for name in names:
        if isinstance(value, dict) and name in value:
            return value[name]
        if hasattr(value, name):
            return getattr(value, name)
    return None


def _next_or_none(iterator):
    return next(iterator, None)
