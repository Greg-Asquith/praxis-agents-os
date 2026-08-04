# apps/api/services/storage/providers/s3.py

"""Amazon S3 provider for the storage contract."""

from __future__ import annotations

import asyncio
import json
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
from services.storage.workspace_buckets import s3_workspace_bucket_name, workspace_id_for_ref

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
        workspace_bucket_prefix: str,
        region_name: str,
        account_id: str,
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
        self.workspace_bucket_prefix = _require_setting(
            workspace_bucket_prefix,
            "WORKSPACE_BUCKET_PREFIX",
            provider_key=self.provider_key,
        )
        self.region_name = _require_setting(
            region_name, "AWS_REGION", provider_key=self.provider_key
        )
        self.account_id = _require_setting(
            account_id, "AWS_ACCOUNT_ID", provider_key=self.provider_key
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
        self._ensured_workspace_ids: OrderedDict[UUID, None] = OrderedDict()
        self._ensured_workspace_ids_lock = threading.Lock()

    @classmethod
    def from_settings(cls, settings: Settings) -> S3StorageProvider:
        return cls(
            public_bucket_name=settings.S3_PUBLIC_ASSETS_BUCKET,
            workspace_bucket_prefix=settings.WORKSPACE_BUCKET_PREFIX,
            region_name=settings.AWS_REGION,
            account_id=settings.AWS_ACCOUNT_ID,
            public_assets_base_url=settings.PUBLIC_ASSETS_BASE_URL or "",
            public_cache_control=settings.PUBLIC_ASSETS_CACHE_CONTROL,
            access_key_id=settings.AWS_ACCESS_KEY_ID,
            secret_access_key=settings.AWS_SECRET_ACCESS_KEY.get_secret_value(),
        )

    async def ensure_workspace_bucket(self, workspace_id: UUID) -> None:
        """Create and harden the S3 bucket dedicated to one workspace."""
        with self._ensured_workspace_ids_lock:
            if workspace_id in self._ensured_workspace_ids:
                self._ensured_workspace_ids.move_to_end(workspace_id)
                return
        bucket_name = self._workspace_bucket_name(workspace_id)
        try:
            await asyncio.to_thread(self.client.head_bucket, Bucket=bucket_name)
        except Exception as exc:
            if not _is_not_found_error(exc):
                raise StorageError(
                    "Failed to inspect workspace S3 bucket",
                    provider_key=self.provider_key,
                    operation="ensure_workspace_bucket",
                    bucket=bucket_name,
                    original_error=exc,
                ) from exc
            create_params: dict[str, Any] = {
                "Bucket": bucket_name,
                "BucketNamespace": "account-regional",
                "ObjectOwnership": "BucketOwnerEnforced",
            }
            if self.region_name != "us-east-1":
                create_params["CreateBucketConfiguration"] = {
                    "LocationConstraint": self.region_name
                }
            try:
                await asyncio.to_thread(self.client.create_bucket, **create_params)
            except Exception as create_exc:
                if not _is_bucket_already_owned_error(create_exc):
                    raise StorageError(
                        "Failed to create workspace S3 bucket",
                        provider_key=self.provider_key,
                        operation="ensure_workspace_bucket",
                        bucket=bucket_name,
                        original_error=create_exc,
                    ) from create_exc

        try:
            await asyncio.to_thread(
                self.client.put_public_access_block,
                Bucket=bucket_name,
                PublicAccessBlockConfiguration={
                    "BlockPublicAcls": True,
                    "IgnorePublicAcls": True,
                    "BlockPublicPolicy": True,
                    "RestrictPublicBuckets": True,
                },
            )
            await asyncio.to_thread(
                self.client.put_bucket_encryption,
                Bucket=bucket_name,
                ServerSideEncryptionConfiguration={
                    "Rules": [
                        {
                            "ApplyServerSideEncryptionByDefault": {"SSEAlgorithm": "AES256"},
                            "BucketKeyEnabled": True,
                            "BlockedEncryptionTypes": {"EncryptionType": ["SSE-C"]},
                        }
                    ]
                },
            )
            await asyncio.to_thread(
                self.client.put_bucket_ownership_controls,
                Bucket=bucket_name,
                OwnershipControls={
                    "Rules": [{"ObjectOwnership": "BucketOwnerEnforced"}],
                },
            )
            await asyncio.to_thread(
                self.client.put_bucket_versioning,
                Bucket=bucket_name,
                VersioningConfiguration={"Status": "Enabled"},
            )
            await self._ensure_https_only_policy(bucket_name)
            try:
                tag_response = await asyncio.to_thread(
                    self.client.get_bucket_tagging,
                    Bucket=bucket_name,
                )
            except Exception as tag_exc:
                if not _is_no_such_tag_set_error(tag_exc):
                    raise
                existing_tags = []
            else:
                existing_tags = tag_response.get("TagSet", [])
            tags_by_key = {
                str(tag["Key"]): {"Key": str(tag["Key"]), "Value": str(tag["Value"])}
                for tag in existing_tags
            }
            tags_by_key["praxis-workspace"] = {
                "Key": "praxis-workspace",
                "Value": str(workspace_id),
            }
            await asyncio.to_thread(
                self.client.put_bucket_tagging,
                Bucket=bucket_name,
                Tagging={"TagSet": list(tags_by_key.values())},
            )
        except Exception as exc:
            raise StorageError(
                "Failed to harden workspace S3 bucket",
                provider_key=self.provider_key,
                operation="ensure_workspace_bucket",
                bucket=bucket_name,
                original_error=exc,
            ) from exc
        with self._ensured_workspace_ids_lock:
            self._ensured_workspace_ids[workspace_id] = None
            if len(self._ensured_workspace_ids) > 256:
                self._ensured_workspace_ids.popitem(last=False)

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

        params: dict[str, Any] = {
            "Bucket": self._bucket_name(ref),
            "Key": ref.key,
            "Body": data,
        }
        if content_type:
            params["ContentType"] = content_type
        if resolved_cache_control:
            params["CacheControl"] = resolved_cache_control
        if metadata:
            params["Metadata"] = _string_metadata(metadata)
        if not overwrite:
            params["IfNoneMatch"] = "*"

        try:
            await asyncio.to_thread(self.client.put_object, **params)
        except Exception as exc:
            if _is_precondition_error(exc):
                raise StoragePreconditionError(
                    "Storage object already exists",
                    provider_key=self.provider_key,
                    operation="put_object",
                    bucket=ref.bucket.value,
                    object_key=ref.key,
                    original_error=exc,
                ) from exc
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
                Bucket=self._bucket_name(ref),
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

    async def stream_object(self, ref: StorageObjectRef):
        try:
            response = await asyncio.to_thread(
                self.client.get_object,
                Bucket=self._bucket_name(ref),
                Key=ref.key,
            )
            body = response["Body"]
        except Exception as exc:
            if _is_not_found_error(exc):
                raise StorageNotFoundError(
                    "Storage object not found",
                    provider_key=self.provider_key,
                    operation="stream_object",
                    bucket=ref.bucket.value,
                    object_key=ref.key,
                ) from exc
            raise StorageError(
                "Failed to stream S3 object",
                provider_key=self.provider_key,
                operation="stream_object",
                bucket=ref.bucket.value,
                object_key=ref.key,
                original_error=exc,
            ) from exc

        try:
            iter_chunks = getattr(body, "iter_chunks", None)
            if callable(iter_chunks):
                iterator = iter_chunks(chunk_size=STORAGE_STREAM_CHUNK_SIZE)
                while True:
                    chunk = await asyncio.to_thread(_next_or_none, iterator)
                    if chunk is None:
                        break
                    if chunk:
                        yield chunk
                return

            while True:
                chunk = await asyncio.to_thread(body.read, STORAGE_STREAM_CHUNK_SIZE)
                if not chunk:
                    break
                yield chunk
        except Exception as exc:
            raise StorageError(
                "Failed to stream S3 object",
                provider_key=self.provider_key,
                operation="stream_object",
                bucket=ref.bucket.value,
                object_key=ref.key,
                original_error=exc,
            ) from exc
        finally:
            close = getattr(body, "close", None)
            if callable(close):
                close()

    async def stat_object(self, ref: StorageObjectRef) -> StoredObject | None:
        try:
            response = await asyncio.to_thread(
                self.client.head_object,
                Bucket=self._bucket_name(ref),
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
                Bucket=self._bucket_name(ref),
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
        bucket_name = self._bucket_name(source)
        try:
            await asyncio.to_thread(
                self.client.copy_object,
                Bucket=bucket_name,
                Key=destination.key,
                CopySource={"Bucket": bucket_name, "Key": source.key},
                CopySourceIfMatch=f'"{expected_source_etag}"',
                IfNoneMatch="*",
                MetadataDirective="COPY",
            )
        except Exception as exc:
            if _is_precondition_error(exc):
                raise StoragePreconditionError(
                    "Storage promotion precondition failed",
                    provider_key=self.provider_key,
                    operation="promote_object",
                    bucket=destination.bucket.value,
                    object_key=destination.key,
                    original_error=exc,
                ) from exc
            if _is_not_found_error(exc):
                raise StorageNotFoundError(
                    "Storage promotion source was not found",
                    provider_key=self.provider_key,
                    operation="promote_object",
                    bucket=source.bucket.value,
                    object_key=source.key,
                    original_error=exc,
                ) from exc
            raise StorageError(
                "Failed to promote S3 object",
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
        try:
            url = await asyncio.to_thread(
                self.client.generate_presigned_url,
                "put_object",
                Params={
                    "Bucket": self._bucket_name(ref),
                    "Key": ref.key,
                    "ContentType": normalized_content_type,
                    "IfNoneMatch": "*",
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
            headers={"content-type": normalized_content_type, "if-none-match": "*"},
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

        params = {"Bucket": self._bucket_name(ref), "Key": ref.key}
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

    def _bucket_name(self, ref: StorageObjectRef) -> str:
        workspace_id = workspace_id_for_ref(ref)
        if workspace_id is None:
            return self.public_bucket_name
        return self._workspace_bucket_name(workspace_id)

    def _workspace_bucket_name(self, workspace_id: UUID) -> str:
        return s3_workspace_bucket_name(
            self.workspace_bucket_prefix,
            workspace_id,
            account_id=self.account_id,
            region=self.region_name,
        )

    async def _ensure_https_only_policy(self, bucket_name: str) -> None:
        try:
            response = await asyncio.to_thread(
                self.client.get_bucket_policy,
                Bucket=bucket_name,
            )
        except Exception as exc:
            if not _is_no_such_bucket_policy_error(exc):
                raise
            policy: dict[str, Any] = {"Version": "2012-10-17", "Statement": []}
        else:
            policy = json.loads(response["Policy"])

        statements = policy.get("Statement")
        if isinstance(statements, dict):
            statements = [statements]
        elif not isinstance(statements, list):
            raise StorageValidationError(
                "Workspace S3 bucket policy must contain a Statement list",
                provider_key=self.provider_key,
                operation="ensure_workspace_bucket",
                bucket=bucket_name,
            )
        https_only_statement = {
            "Sid": "DenyInsecureTransport",
            "Effect": "Deny",
            "Principal": "*",
            "Action": "s3:*",
            "Resource": [f"arn:aws:s3:::{bucket_name}", f"arn:aws:s3:::{bucket_name}/*"],
            "Condition": {"Bool": {"aws:SecureTransport": "false"}},
        }
        policy["Statement"] = [
            statement
            for statement in statements
            if not isinstance(statement, dict) or statement.get("Sid") != "DenyInsecureTransport"
        ] + [https_only_statement]
        await asyncio.to_thread(
            self.client.put_bucket_policy,
            Bucket=bucket_name,
            Policy=json.dumps(policy, separators=(",", ":"), sort_keys=True),
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


def _is_precondition_error(exc: Exception) -> bool:
    response = getattr(exc, "response", None)
    if not isinstance(response, dict):
        return getattr(exc, "status_code", None) in {409, 412}
    code = str(response.get("Error", {}).get("Code", ""))
    status = response.get("ResponseMetadata", {}).get("HTTPStatusCode")
    return code in {
        "409",
        "412",
        "ConditionalRequestConflict",
        "PreconditionFailed",
    } or status in {409, 412}


def _is_bucket_already_owned_error(exc: Exception) -> bool:
    response = getattr(exc, "response", None)
    if not isinstance(response, dict):
        return False
    return str(response.get("Error", {}).get("Code", "")) == "BucketAlreadyOwnedByYou"


def _is_no_such_tag_set_error(exc: Exception) -> bool:
    response = getattr(exc, "response", None)
    if not isinstance(response, dict):
        return False
    return str(response.get("Error", {}).get("Code", "")) == "NoSuchTagSet"


def _is_no_such_bucket_policy_error(exc: Exception) -> bool:
    response = getattr(exc, "response", None)
    if not isinstance(response, dict):
        return False
    return str(response.get("Error", {}).get("Code", "")) == "NoSuchBucketPolicy"


def _next_or_none(iterator):
    return next(iterator, None)
