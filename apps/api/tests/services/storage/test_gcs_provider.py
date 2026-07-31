# apps/api/tests/services/storage/test_gcs_provider.py

"""GCS storage provider tests."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from services.storage.domain import StorageBucket, make_storage_object_ref
from services.storage.errors import (
    StorageNotFoundError,
    StoragePreconditionError,
    StorageProviderUnavailableError,
)
from services.storage.providers.gcs import GcsStorageProvider

pytestmark = pytest.mark.asyncio


class _GcsNotFoundError(Exception):
    code = 404


class _GcsPreconditionError(Exception):
    code = 412


class _FakeGcsBlob:
    def __init__(self, bucket: _FakeGcsBucket, key: str) -> None:
        self.bucket = bucket
        self.key = key
        self.cache_control = None
        self.metadata = {}
        self.size = None
        self.etag = None
        self.md5_hash = None
        self.generation = None
        self.content_type = None
        self.updated = None

    def upload_from_string(
        self,
        data: bytes,
        *,
        content_type: str | None = None,
        if_generation_match: int | None = None,
    ) -> None:
        if if_generation_match == 0 and self.key in self.bucket.objects:
            raise _GcsPreconditionError()
        self.bucket.objects[self.key] = {
            "data": data,
            "content_type": content_type,
            "cache_control": self.cache_control,
            "metadata": dict(self.metadata),
            "etag": "gcs-etag",
            "generation": self.bucket.next_generation,
            "updated": datetime(2026, 7, 1, tzinfo=UTC),
        }
        self.bucket.next_generation += 1

    def exists(self) -> bool:
        return self.key in self.bucket.objects

    def download_as_bytes(self) -> bytes:
        return self.bucket.objects[self.key]["data"]

    def reload(self) -> None:
        obj = self.bucket.objects.get(self.key)
        if obj is None:
            raise _GcsNotFoundError()
        self.size = len(obj["data"])
        self.content_type = obj["content_type"]
        self.cache_control = obj["cache_control"]
        self.metadata = obj["metadata"]
        self.etag = obj["etag"]
        self.generation = obj["generation"]
        self.updated = obj["updated"]

    def delete(self) -> None:
        self.bucket.objects.pop(self.key, None)

    def generate_signed_url(self, **kwargs) -> str:
        self.bucket.signed_calls.append({"key": self.key, **kwargs})
        return f"https://gcs-signed.example/{self.key}"


class _FakeGcsBucket:
    def __init__(self, name: str) -> None:
        self.name = name
        self.objects: dict[str, dict] = {}
        self.signed_calls: list[dict] = []
        self.copy_calls: list[dict] = []
        self.next_generation = 1

    def blob(self, key: str) -> _FakeGcsBlob:
        return _FakeGcsBlob(self, key)

    def copy_blob(self, source, destination_bucket, **kwargs):
        self.copy_calls.append({"source": source.key, **kwargs})
        destination_key = kwargs["new_name"]
        source_obj = self.objects.get(source.key)
        if source_obj is None:
            raise _GcsNotFoundError()
        if kwargs["if_generation_match"] == 0 and destination_key in destination_bucket.objects:
            raise _GcsPreconditionError()
        if source_obj["generation"] != kwargs["if_source_generation_match"]:
            raise _GcsPreconditionError()
        destination_bucket.objects[destination_key] = {
            **source_obj,
            "generation": destination_bucket.next_generation,
        }
        destination_bucket.next_generation += 1
        return destination_bucket.blob(destination_key)


class _FakeGcsClient:
    def __init__(self) -> None:
        self.buckets: dict[str, _FakeGcsBucket] = {}

    def bucket(self, name: str) -> _FakeGcsBucket:
        self.buckets.setdefault(name, _FakeGcsBucket(name))
        return self.buckets[name]


def _provider(client: _FakeGcsClient) -> GcsStorageProvider:
    return GcsStorageProvider(
        public_bucket_name="public-bucket",
        private_bucket_name="private-bucket",
        public_assets_base_url="https://cdn.example",
        public_cache_control="public, max-age=60",
        client=client,
    )


async def test_gcs_provider_put_get_stat_and_delete_object() -> None:
    client = _FakeGcsClient()
    provider = _provider(client)
    ref = make_storage_object_ref(StorageBucket.PUBLIC, "users/u_1/avatar/me.png")

    stored = await provider.put_object(
        ref,
        b"png",
        content_type="image/png",
        metadata={"purpose": "avatar"},
    )

    assert stored.size_bytes == 3
    assert stored.etag == "gcs-etag"
    assert stored.content_type == "image/png"
    assert stored.cache_control == "public, max-age=60"
    assert stored.metadata == {"purpose": "avatar"}
    assert stored.public_url == "https://cdn.example/users/u_1/avatar/me.png"
    assert await provider.get_object(ref) == b"png"

    assert await provider.delete_object(ref) is True
    assert await provider.stat_object(ref) is None
    assert await provider.delete_object(ref) is False


async def test_gcs_provider_maps_get_not_found_to_storage_error() -> None:
    provider = _provider(_FakeGcsClient())
    ref = make_storage_object_ref(StorageBucket.PRIVATE, "runs/run_1/missing.txt")

    with pytest.raises(StorageNotFoundError):
        await provider.get_object(ref)

    assert await provider.stat_object(ref) is None


async def test_gcs_provider_signed_urls_bind_content_type_and_disposition() -> None:
    client = _FakeGcsClient()
    provider = _provider(client)
    ref = make_storage_object_ref(StorageBucket.PRIVATE, "runs/run_1/output.txt")

    upload = await provider.create_signed_upload(
        ref,
        content_type="text/plain",
        expires_in=timedelta(minutes=5),
    )
    download = await provider.create_signed_download(
        ref,
        expires_in=timedelta(minutes=5),
        force_download=True,
        filename="output.txt",
    )

    signed_calls = client.bucket("private-bucket").signed_calls
    assert upload.headers == {"content-type": "text/plain"}
    assert signed_calls[0]["method"] == "PUT"
    assert signed_calls[0]["content_type"] == "text/plain"
    assert signed_calls[0]["query_parameters"] == {"ifGenerationMatch": "0"}
    assert download.headers == {"content-disposition": 'attachment; filename="output.txt"'}
    assert signed_calls[1]["method"] == "GET"
    assert signed_calls[1]["response_disposition"] == 'attachment; filename="output.txt"'


async def test_gcs_native_public_url_is_used_without_cdn_base() -> None:
    provider = GcsStorageProvider(
        public_bucket_name="public-bucket",
        private_bucket_name="private-bucket",
        client=_FakeGcsClient(),
    )
    ref = make_storage_object_ref(StorageBucket.PUBLIC, "users/u 1/avatar/me.png")

    assert (
        provider.public_url(ref)
        == "https://storage.googleapis.com/public-bucket/users/u%201/avatar/me.png"
    )


async def test_gcs_promotion_is_create_only_and_source_conditional() -> None:
    client = _FakeGcsClient()
    provider = _provider(client)
    source = make_storage_object_ref(StorageBucket.PRIVATE, "uploads/source.txt")
    destination = make_storage_object_ref(StorageBucket.PRIVATE, "files/final.txt")
    source_stored = await provider.put_object(source, b"validated", content_type="text/plain")

    promoted = await provider.promote_object(
        source,
        destination,
        expected_source_etag=source_stored.etag,
    )

    assert await provider.get_object(destination) == b"validated"
    assert promoted.content_type == "text/plain"
    copy_call = client.bucket("private-bucket").copy_calls[0]
    assert copy_call["if_generation_match"] == 0
    assert copy_call["if_source_generation_match"] == copy_call["source_generation"]
    with pytest.raises(StoragePreconditionError):
        await provider.promote_object(
            source,
            destination,
            expected_source_etag=source_stored.etag,
        )


async def test_gcs_provider_missing_required_settings_fail_clearly() -> None:
    with pytest.raises(StorageProviderUnavailableError):
        GcsStorageProvider(
            public_bucket_name="",
            private_bucket_name="private-bucket",
            client=_FakeGcsClient(),
        )
