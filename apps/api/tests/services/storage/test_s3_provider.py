# apps/api/tests/services/storage/test_s3_provider.py

"""S3 storage provider tests."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from io import BytesIO

import pytest

from services.storage.domain import StorageBucket, make_storage_object_ref
from services.storage.errors import StorageNotFoundError, StorageProviderUnavailableError
from services.storage.providers.s3 import S3StorageProvider

pytestmark = pytest.mark.asyncio


class _S3NotFoundError(Exception):
    def __init__(self) -> None:
        super().__init__("S3 object not found")
        self.response = {"Error": {"Code": "NoSuchKey"}}


class _FakeBody(BytesIO):
    closed_by_provider = False

    def close(self) -> None:
        self.closed_by_provider = True
        super().close()


class _FakeS3Client:
    def __init__(self) -> None:
        self.objects: dict[tuple[str, str], dict] = {}
        self.presigned_calls: list[dict] = []
        self.deleted: list[tuple[str, str]] = []

    def put_object(self, **params):
        key = (params["Bucket"], params["Key"])
        self.objects[key] = {
            "body": params["Body"],
            "content_type": params.get("ContentType"),
            "cache_control": params.get("CacheControl"),
            "metadata": params.get("Metadata") or {},
            "etag": '"etag-1"',
            "last_modified": datetime(2026, 7, 1, tzinfo=UTC),
        }

    def head_object(self, **kwargs):
        bucket = kwargs["Bucket"]
        key = kwargs["Key"]
        obj = self.objects.get((bucket, key))
        if obj is None:
            raise _S3NotFoundError()
        return {
            "ContentLength": len(obj["body"]),
            "ContentType": obj["content_type"],
            "CacheControl": obj["cache_control"],
            "Metadata": obj["metadata"],
            "ETag": obj["etag"],
            "LastModified": obj["last_modified"],
        }

    def get_object(self, **kwargs):
        bucket = kwargs["Bucket"]
        key = kwargs["Key"]
        obj = self.objects.get((bucket, key))
        if obj is None:
            raise _S3NotFoundError()
        return {"Body": _FakeBody(obj["body"])}

    def delete_object(self, **kwargs):
        bucket = kwargs["Bucket"]
        key = kwargs["Key"]
        self.objects.pop((bucket, key), None)
        self.deleted.append((bucket, key))

    def generate_presigned_url(self, operation: str, **kwargs):
        self.presigned_calls.append({"operation": operation, **kwargs})
        return f"https://signed.example/{operation}/{kwargs['Params']['Key']}"


def _provider(client: _FakeS3Client) -> S3StorageProvider:
    return S3StorageProvider(
        public_bucket_name="public-bucket",
        private_bucket_name="private-bucket",
        region_name="eu-west-2",
        public_assets_base_url="https://cdn.example",
        public_cache_control="public, max-age=60",
        client=client,
    )


async def test_s3_provider_put_get_stat_and_delete_object() -> None:
    client = _FakeS3Client()
    provider = _provider(client)
    ref = make_storage_object_ref(StorageBucket.PUBLIC, "users/u_1/avatar/me.png")

    stored = await provider.put_object(
        ref,
        b"png",
        content_type="image/png",
        metadata={"purpose": "avatar"},
    )

    assert client.objects[("public-bucket", ref.key)]["cache_control"] == "public, max-age=60"
    assert stored.size_bytes == 3
    assert stored.etag == "etag-1"
    assert stored.content_type == "image/png"
    assert stored.metadata == {"purpose": "avatar"}
    assert stored.public_url == "https://cdn.example/users/u_1/avatar/me.png"
    assert await provider.get_object(ref) == b"png"

    assert await provider.delete_object(ref) is True
    assert await provider.stat_object(ref) is None
    assert await provider.delete_object(ref) is False


async def test_s3_provider_maps_get_not_found_to_storage_error() -> None:
    provider = _provider(_FakeS3Client())
    ref = make_storage_object_ref(StorageBucket.PRIVATE, "runs/run_1/missing.txt")

    with pytest.raises(StorageNotFoundError):
        await provider.get_object(ref)

    assert await provider.stat_object(ref) is None


async def test_s3_provider_signed_urls_bind_content_type_and_disposition() -> None:
    client = _FakeS3Client()
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

    assert upload.headers == {"content-type": "text/plain"}
    assert client.presigned_calls[0]["operation"] == "put_object"
    assert client.presigned_calls[0]["Params"]["ContentType"] == "text/plain"
    assert download.headers == {"content-disposition": 'attachment; filename="output.txt"'}
    assert client.presigned_calls[1]["operation"] == "get_object"
    assert (
        client.presigned_calls[1]["Params"]["ResponseContentDisposition"]
        == 'attachment; filename="output.txt"'
    )


async def test_s3_public_signed_download_returns_public_url() -> None:
    provider = _provider(_FakeS3Client())
    ref = make_storage_object_ref(StorageBucket.PUBLIC, "users/u_1/avatar/me.png")

    download = await provider.create_signed_download(ref, expires_in=timedelta(minutes=5))

    assert download.url == "https://cdn.example/users/u_1/avatar/me.png"


async def test_s3_provider_missing_required_settings_fail_clearly() -> None:
    with pytest.raises(StorageProviderUnavailableError):
        S3StorageProvider(
            public_bucket_name="",
            private_bucket_name="private-bucket",
            region_name="eu-west-2",
            public_assets_base_url="https://cdn.example",
            client=_FakeS3Client(),
        )
