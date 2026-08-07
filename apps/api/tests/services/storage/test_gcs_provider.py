# apps/api/tests/services/storage/test_gcs_provider.py

"""GCS storage provider tests."""

from __future__ import annotations

import asyncio
import logging
import threading
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest

from services.storage.domain import StorageBucket, make_storage_object_ref
from services.storage.errors import (
    StorageError,
    StorageNotFoundError,
    StoragePreconditionError,
    StorageProviderUnavailableError,
)
from services.storage.providers.gcs import GcsStorageProvider

pytestmark = pytest.mark.asyncio
WORKSPACE_ID = UUID("11111111-1111-4111-8111-111111111111")
WORKSPACE_BUCKET = f"praxis-test-{WORKSPACE_ID}"


def _private_key(suffix: str) -> str:
    return f"workspaces/{WORKSPACE_ID}/{suffix}"


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
        if self.bucket.signed_error is not None:
            raise self.bucket.signed_error
        self.bucket.signed_calls.append({"key": self.key, **kwargs})
        return f"https://gcs-signed.example/{self.key}"


class _FakeGcsBucket:
    def __init__(self, client: _FakeGcsClient, name: str) -> None:
        self.client = client
        self.name = name
        self.objects: dict[str, dict] = {}
        self.signed_calls: list[dict] = []
        self.signed_error: Exception | None = None
        self.copy_calls: list[dict] = []
        self.next_generation = 1
        self.labels: dict[str, str] = {}
        self.cors: list[dict[str, object]] = []
        self.iam_configuration = SimpleNamespace(
            uniform_bucket_level_access_enabled=False,
            public_access_prevention=None,
        )
        self.versioning_enabled = False
        self.soft_delete_policy = SimpleNamespace(retention_duration_seconds=None)
        self.patch_calls = 0

    def reload(self) -> None:
        if self.name not in self.client.existing_buckets:
            raise _GcsNotFoundError()

    def patch(self) -> None:
        self.patch_calls += 1

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
        self.existing_buckets = {"public-bucket"}
        self.create_calls: list[dict] = []

    def bucket(self, name: str) -> _FakeGcsBucket:
        self.buckets.setdefault(name, _FakeGcsBucket(self, name))
        return self.buckets[name]

    def create_bucket(self, bucket: _FakeGcsBucket, **kwargs) -> _FakeGcsBucket:
        self.create_calls.append({"bucket": bucket.name, **kwargs})
        self.existing_buckets.add(bucket.name)
        return bucket


class _FakeMetadataCredentials:
    def __init__(self) -> None:
        self.valid = False
        self.service_account_email = "default"
        self.token = None
        self.refresh_calls = 0

    def refresh(self, _request) -> None:
        self.valid = True
        self.service_account_email = "praxis@example.iam.gserviceaccount.com"
        self.token = "access-token"
        self.refresh_calls += 1


def _provider(client: _FakeGcsClient) -> GcsStorageProvider:
    return GcsStorageProvider(
        public_bucket_name="public-bucket",
        workspace_bucket_prefix="praxis-test",
        workspace_bucket_location="europe-west2",
        public_assets_base_url="https://cdn.example",
        public_cache_control="public, max-age=60",
        project_id="praxis-test-project",
        cors_origins=(
            "https://app.example",
            "https://admin.example/",
            "https://app.example/",
        ),
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
    ref = make_storage_object_ref(StorageBucket.PRIVATE, _private_key("missing.txt"))

    with pytest.raises(StorageNotFoundError):
        await provider.get_object(ref)

    assert await provider.stat_object(ref) is None


async def test_gcs_provider_signed_urls_bind_content_type_and_disposition() -> None:
    client = _FakeGcsClient()
    provider = _provider(client)
    ref = make_storage_object_ref(StorageBucket.PRIVATE, _private_key("output.txt"))

    upload = await provider.create_signed_upload(
        ref,
        content_type="text/plain",
        expected_size_bytes=4,
        expires_in=timedelta(minutes=5),
    )
    download = await provider.create_signed_download(
        ref,
        expires_in=timedelta(minutes=5),
        force_download=True,
        filename="output.txt",
    )

    signed_calls = client.bucket(WORKSPACE_BUCKET).signed_calls
    assert upload.headers == {
        "content-type": "text/plain",
        "x-goog-if-generation-match": "0",
    }
    assert signed_calls[0]["method"] == "PUT"
    assert signed_calls[0]["content_type"] == "text/plain"
    assert signed_calls[0]["headers"] == {
        "content-length": "4",
        "x-goog-if-generation-match": "0",
    }
    assert download.headers == {"content-disposition": 'attachment; filename="output.txt"'}
    assert signed_calls[1]["method"] == "GET"
    assert signed_calls[1]["response_disposition"] == 'attachment; filename="output.txt"'


async def test_gcs_signed_urls_use_iam_signing_for_metadata_credentials() -> None:
    client = _FakeGcsClient()
    credentials = _FakeMetadataCredentials()
    client._credentials = credentials
    provider = _provider(client)
    ref = make_storage_object_ref(StorageBucket.PRIVATE, _private_key("output.txt"))

    await provider.create_signed_upload(
        ref,
        content_type="text/plain",
        expected_size_bytes=4,
        expires_in=timedelta(minutes=5),
    )
    await provider.create_signed_download(ref, expires_in=timedelta(minutes=5))

    signed_calls = client.bucket(WORKSPACE_BUCKET).signed_calls
    assert credentials.refresh_calls == 1
    assert signed_calls[0]["service_account_email"] == credentials.service_account_email
    assert signed_calls[0]["access_token"] == credentials.token
    assert signed_calls[1]["service_account_email"] == credentials.service_account_email
    assert signed_calls[1]["access_token"] == credentials.token


async def test_gcs_signed_url_failure_logs_underlying_google_error_type(
    caplog: pytest.LogCaptureFixture,
) -> None:
    client = _FakeGcsClient()
    provider = _provider(client)
    bucket = client.bucket(WORKSPACE_BUCKET)
    bucket.signed_error = RuntimeError("IAM signBlob denied")
    ref = make_storage_object_ref(StorageBucket.PRIVATE, _private_key("output.txt"))

    with caplog.at_level(logging.ERROR), pytest.raises(StorageError):
        await provider.create_signed_upload(
            ref,
            content_type="text/plain",
            expected_size_bytes=4,
            expires_in=timedelta(minutes=5),
        )

    record = next(
        record
        for record in caplog.records
        if record.message == "GCS signed upload URL generation failed"
    )
    assert record.error_type == "RuntimeError"
    assert record.exc_info is not None


async def test_gcs_native_public_url_is_used_without_cdn_base() -> None:
    provider = GcsStorageProvider(
        public_bucket_name="public-bucket",
        workspace_bucket_prefix="praxis-test",
        workspace_bucket_location="europe-west2",
        project_id="praxis-test-project",
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
    source = make_storage_object_ref(StorageBucket.PRIVATE, _private_key("uploads/source.txt"))
    destination = make_storage_object_ref(StorageBucket.PRIVATE, _private_key("files/final.txt"))
    source_stored = await provider.put_object(source, b"validated", content_type="text/plain")

    promoted = await provider.promote_object(
        source,
        destination,
        expected_source_etag=source_stored.etag,
    )

    assert await provider.get_object(destination) == b"validated"
    assert promoted.content_type == "text/plain"
    copy_call = client.bucket(WORKSPACE_BUCKET).copy_calls[0]
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
            workspace_bucket_prefix="praxis-test",
            workspace_bucket_location="europe-west2",
            project_id="praxis-test-project",
            client=_FakeGcsClient(),
        )


async def test_gcs_workspace_bucket_is_hardened_and_handle_is_cached() -> None:
    client = _FakeGcsClient()
    provider = _provider(client)

    await provider.ensure_workspace_bucket(WORKSPACE_ID)
    await provider.ensure_workspace_bucket(WORKSPACE_ID)

    bucket = client.bucket(WORKSPACE_BUCKET)
    assert bucket.iam_configuration.uniform_bucket_level_access_enabled is True
    assert bucket.iam_configuration.public_access_prevention == "enforced"
    assert bucket.versioning_enabled is True
    assert bucket.soft_delete_policy.retention_duration_seconds == 30 * 24 * 60 * 60
    assert bucket.labels == {"praxis-workspace": str(WORKSPACE_ID)}
    assert bucket.cors == [
        {
            "origin": ["https://app.example", "https://admin.example"],
            "method": ["GET", "HEAD", "PUT"],
            "responseHeader": [
                "Content-Length",
                "Content-Type",
                "ETag",
                "x-goog-generation",
                "x-goog-if-generation-match",
            ],
            "maxAgeSeconds": 3600,
        }
    ]
    assert client.create_calls == [
        {
            "bucket": WORKSPACE_BUCKET,
            "project": "praxis-test-project",
            "location": "europe-west2",
        }
    ]
    assert provider._workspace_bucket(WORKSPACE_ID) is bucket


async def test_gcs_provisioning_restores_handle_if_it_is_evicted_while_awaiting() -> None:
    client = _FakeGcsClient()
    client.existing_buckets.add(WORKSPACE_BUCKET)
    provider = _provider(client)
    bucket = provider._workspace_bucket(WORKSPACE_ID)
    reload_started = threading.Event()
    release_reload = threading.Event()
    original_reload = bucket.reload

    def blocking_reload() -> None:
        reload_started.set()
        assert release_reload.wait(timeout=5)
        original_reload()

    bucket.reload = blocking_reload
    provisioning = asyncio.create_task(provider.ensure_workspace_bucket(WORKSPACE_ID))
    assert await asyncio.to_thread(reload_started.wait, 5)
    for _index in range(256):
        provider._workspace_bucket(uuid4())
    assert WORKSPACE_ID not in provider._workspace_buckets

    release_reload.set()
    await provisioning

    assert provider._workspace_buckets[WORKSPACE_ID] is bucket
    await provider.ensure_workspace_bucket(WORKSPACE_ID)
