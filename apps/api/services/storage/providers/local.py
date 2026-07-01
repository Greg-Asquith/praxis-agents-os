# apps/api/services/storage/providers/local.py

"""Local filesystem storage provider."""

from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.parse import urlencode

from core.settings import Settings
from services.storage.domain import (
    SignedDownload,
    SignedUpload,
    StorageBucket,
    StorageObjectRef,
    StoredObject,
)
from services.storage.errors import (
    StorageNotFoundError,
    StorageSignatureError,
    StorageValidationError,
)
from services.storage.paths import build_content_disposition, quote_object_key


class LocalStorageProvider:
    """Filesystem-backed object storage for local development."""

    provider_key = "local_fs"

    def __init__(
        self,
        *,
        root: str | Path,
        app_base_url: str,
        api_prefix: str,
        secret_key: str,
        public_assets_base_url: str | None = None,
        public_cache_control: str | None = None,
    ) -> None:
        self.root = Path(root).resolve()
        self.public_root = self.root / StorageBucket.PUBLIC.value
        self.private_root = self.root / StorageBucket.PRIVATE.value
        self.metadata_root = self.root / ".metadata"
        self.public_metadata_root = self.metadata_root / StorageBucket.PUBLIC.value
        self.private_metadata_root = self.metadata_root / StorageBucket.PRIVATE.value
        self.app_base_url = app_base_url.rstrip("/")
        self.api_prefix = api_prefix.rstrip("/")
        self.secret_key = secret_key
        self.public_assets_base_url = public_assets_base_url.rstrip("/") if public_assets_base_url else None
        self.public_cache_control = public_cache_control
        self.public_root.mkdir(parents=True, exist_ok=True)
        self.private_root.mkdir(parents=True, exist_ok=True)
        self.public_metadata_root.mkdir(parents=True, exist_ok=True)
        self.private_metadata_root.mkdir(parents=True, exist_ok=True)

    @classmethod
    def from_settings(cls, settings: Settings) -> LocalStorageProvider:
        return cls(
            root=settings.LOCAL_STORAGE_ROOT,
            app_base_url=settings.APP_BASE_URL,
            api_prefix=settings.API_V1_PREFIX,
            secret_key=settings.SECRET_KEY.get_secret_value(),
            public_assets_base_url=settings.PUBLIC_ASSETS_BASE_URL,
            public_cache_control=settings.PUBLIC_ASSETS_CACHE_CONTROL,
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
        path = self.filesystem_path(ref)
        resolved_cache_control = cache_control
        if ref.bucket == StorageBucket.PUBLIC and resolved_cache_control is None:
            resolved_cache_control = self.public_cache_control

        etag = _content_hash(data)
        stored_metadata = {
            "content_type": content_type,
            "cache_control": resolved_cache_control,
            "metadata": metadata or {},
            "etag": etag,
            "updated_at": datetime.now(UTC).isoformat(),
        }

        await asyncio.to_thread(path.parent.mkdir, parents=True, exist_ok=True)
        await asyncio.to_thread(path.write_bytes, data)
        metadata_path = self._metadata_path(ref)
        await asyncio.to_thread(metadata_path.parent.mkdir, parents=True, exist_ok=True)
        await asyncio.to_thread(
            metadata_path.write_text,
            json.dumps(stored_metadata, sort_keys=True),
            "utf-8",
        )
        stat = await self.stat_object(ref)
        if stat is None:
            raise StorageNotFoundError(
                "Stored object could not be read after write",
                provider_key=self.provider_key,
                operation="put_object",
                bucket=ref.bucket.value,
                object_key=ref.key,
            )
        return stat

    async def get_object(self, ref: StorageObjectRef) -> bytes:
        path = self.filesystem_path(ref)
        if not await asyncio.to_thread(path.is_file):
            raise StorageNotFoundError(
                "Storage object not found",
                provider_key=self.provider_key,
                operation="get_object",
                bucket=ref.bucket.value,
                object_key=ref.key,
            )
        return await asyncio.to_thread(path.read_bytes)

    async def stat_object(self, ref: StorageObjectRef) -> StoredObject | None:
        path = self.filesystem_path(ref)
        if not await asyncio.to_thread(path.is_file):
            return None

        stat = await asyncio.to_thread(path.stat)
        metadata = await self._read_metadata(ref)
        app_metadata = metadata.get("metadata") if isinstance(metadata.get("metadata"), dict) else {}
        etag = _optional_str(metadata.get("etag")) or _stat_fingerprint(stat)
        updated_at = _parse_datetime(metadata.get("updated_at")) or datetime.fromtimestamp(stat.st_mtime, tz=UTC)
        return StoredObject(
            ref=ref,
            size_bytes=stat.st_size,
            etag=etag,
            content_type=_optional_str(metadata.get("content_type")),
            cache_control=_optional_str(metadata.get("cache_control")),
            metadata={str(key): str(value) for key, value in app_metadata.items()},
            public_url=self.public_url(ref),
            updated_at=updated_at,
        )

    async def delete_object(self, ref: StorageObjectRef) -> bool:
        path = self.filesystem_path(ref)
        metadata_path = self._metadata_path(ref)
        if not await asyncio.to_thread(path.exists):
            if await asyncio.to_thread(metadata_path.exists):
                await asyncio.to_thread(metadata_path.unlink)
            return False

        await asyncio.to_thread(path.unlink)
        if await asyncio.to_thread(metadata_path.exists):
            await asyncio.to_thread(metadata_path.unlink)
        return True

    async def create_signed_upload(
        self,
        ref: StorageObjectRef,
        *,
        content_type: str,
        expires_in: timedelta,
    ) -> SignedUpload:
        normalized_content_type = content_type.strip()
        if not normalized_content_type:
            raise StorageValidationError(
                "Signed upload content_type is required",
                provider_key=self.provider_key,
                operation="create_signed_upload",
                bucket=ref.bucket.value,
                object_key=ref.key,
            )

        expires_at = datetime.now(UTC) + expires_in
        expires = int(expires_at.timestamp())
        query = {
            "content_type": normalized_content_type,
            "expires": str(expires),
            "sig": self._signature(
                action="upload",
                ref=ref,
                expires=expires,
                content_type=normalized_content_type,
            ),
        }
        url = (
            f"{self._local_route_base()}/upload/{ref.bucket.value}/{quote_object_key(ref.key)}"
            f"?{urlencode(query)}"
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

        expires = int(expires_at.timestamp())
        query = {
            "expires": str(expires),
            "sig": self._signature(
                action="download",
                ref=ref,
                expires=expires,
                force_download=force_download,
                filename=filename or "",
            ),
        }
        if force_download:
            query["download"] = "1"
        if filename:
            query["filename"] = filename
        url = f"{self._local_route_base()}/private/{quote_object_key(ref.key)}?{urlencode(query)}"
        headers = {}
        disposition = build_content_disposition(filename) if force_download else None
        if disposition:
            headers["content-disposition"] = disposition
        return SignedDownload(ref=ref, url=url, headers=headers, expires_at=expires_at)

    def public_url(self, ref: StorageObjectRef) -> str | None:
        if ref.bucket != StorageBucket.PUBLIC:
            return None
        base = self.public_assets_base_url or f"{self._local_route_base()}/public"
        return f"{base}/{quote_object_key(ref.key)}"

    def filesystem_path(self, ref: StorageObjectRef) -> Path:
        root = self._bucket_root(ref.bucket)
        relative = Path(ref.key)
        resolved = (root / relative).resolve()
        if root not in resolved.parents and resolved != root:
            raise StorageValidationError(
                "Storage object path escaped its bucket root",
                provider_key=self.provider_key,
                operation="filesystem_path",
                bucket=ref.bucket.value,
                object_key=ref.key,
            )
        return resolved

    def verify_signature(
        self,
        *,
        action: str,
        ref: StorageObjectRef,
        expires: int,
        signature: str,
        content_type: str = "",
        force_download: bool = False,
        filename: str = "",
    ) -> bool:
        if expires < int(datetime.now(UTC).timestamp()):
            return False
        expected = self._signature(
            action=action,
            ref=ref,
            expires=expires,
            content_type=content_type,
            force_download=force_download,
            filename=filename,
        )
        return hmac.compare_digest(signature, expected)

    def require_valid_signature(
        self,
        *,
        action: str,
        ref: StorageObjectRef,
        expires: int,
        signature: str,
        content_type: str = "",
        force_download: bool = False,
        filename: str = "",
    ) -> None:
        if self.verify_signature(
            action=action,
            ref=ref,
            expires=expires,
            signature=signature,
            content_type=content_type,
            force_download=force_download,
            filename=filename,
        ):
            return

        raise StorageSignatureError(
            "Invalid or expired local storage URL",
            provider_key=self.provider_key,
            operation=action,
            bucket=ref.bucket.value,
            object_key=ref.key,
        )

    def require_valid_upload_signature(
        self,
        ref: StorageObjectRef,
        *,
        expires: int,
        signature: str,
        content_type: str,
    ) -> None:
        self.require_valid_signature(
            action="upload",
            ref=ref,
            expires=expires,
            signature=signature,
            content_type=content_type,
        )

    def require_valid_download_signature(
        self,
        ref: StorageObjectRef,
        *,
        expires: int,
        signature: str,
        force_download: bool = False,
        filename: str = "",
    ) -> None:
        self.require_valid_signature(
            action="download",
            ref=ref,
            expires=expires,
            signature=signature,
            force_download=force_download,
            filename=filename,
        )

    def _bucket_root(self, bucket: StorageBucket) -> Path:
        return self.public_root if bucket == StorageBucket.PUBLIC else self.private_root

    def _metadata_bucket_root(self, bucket: StorageBucket) -> Path:
        return (
            self.public_metadata_root
            if bucket == StorageBucket.PUBLIC
            else self.private_metadata_root
        )

    def _local_route_base(self) -> str:
        return f"{self.app_base_url}{self.api_prefix}/storage"

    def _signature(
        self,
        *,
        action: str,
        ref: StorageObjectRef,
        expires: int,
        content_type: str = "",
        force_download: bool = False,
        filename: str = "",
    ) -> str:
        payload = "\n".join(
            [
                action,
                ref.bucket.value,
                ref.key,
                str(expires),
                content_type,
                "1" if force_download else "0",
                filename,
            ]
        )
        digest = hmac.new(self.secret_key.encode(), payload.encode(), hashlib.sha256).digest()
        return base64.urlsafe_b64encode(digest).decode().rstrip("=")

    def _metadata_path(self, ref: StorageObjectRef) -> Path:
        root = self._metadata_bucket_root(ref.bucket)
        relative = Path(ref.key)
        resolved = (root / relative).with_name(f"{relative.name}.metadata.json").resolve()
        if root not in resolved.parents and resolved != root:
            raise StorageValidationError(
                "Storage metadata path escaped its bucket root",
                provider_key=self.provider_key,
                operation="metadata_path",
                bucket=ref.bucket.value,
                object_key=ref.key,
            )
        return resolved

    async def _read_metadata(self, ref: StorageObjectRef) -> dict[str, object]:
        path = self._metadata_path(ref)
        if not await asyncio.to_thread(path.is_file):
            return {}
        raw = await asyncio.to_thread(path.read_text, "utf-8")
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            return {}
        return parsed if isinstance(parsed, dict) else {}


def _content_hash(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _stat_fingerprint(stat_result) -> str:
    payload = f"{stat_result.st_size}:{stat_result.st_mtime_ns}".encode()
    return f"local-stat-{hashlib.sha256(payload).hexdigest()}"


def _optional_str(value: object) -> str | None:
    if value is None:
        return None
    return str(value)


def _parse_datetime(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)
