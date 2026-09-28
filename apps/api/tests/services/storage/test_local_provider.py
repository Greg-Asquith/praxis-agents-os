# apps/api/tests/services/storage/test_local_provider.py

"""Local filesystem storage provider tests."""

from datetime import timedelta
from urllib.parse import parse_qs, urlsplit
from uuid import UUID

import pytest

from services.storage.domain import StorageBucket, make_storage_object_ref
from services.storage.errors import (
    StoragePreconditionError,
    StorageValidationError,
)
from services.storage.paths import validate_object_key
from services.storage.providers.local import LocalStorageProvider
from services.storage.utils import put_new_object_with_cleanup

pytestmark = pytest.mark.asyncio
WORKSPACE_ID = UUID("11111111-1111-4111-8111-111111111111")


def _private_key(suffix: str) -> str:
    return f"workspaces/{WORKSPACE_ID}/{suffix}"


def _provider(tmp_path) -> LocalStorageProvider:
    return LocalStorageProvider(
        root=tmp_path,
        app_base_url="http://testserver",
        api_prefix="/api/v1",
        secret_key="x" * 40,
        public_cache_control="public, max-age=60",
    )


@pytest.mark.parametrize("platform", [False, True])
async def test_local_provider_put_get_stat_and_delete_object(tmp_path, platform: bool) -> None:
    provider = _provider(tmp_path)
    ref = make_storage_object_ref(
        StorageBucket.PLATFORM_PRIVATE if platform else StorageBucket.PRIVATE,
        "platform/files/hello.txt" if platform else _private_key("files/hello.txt"),
    )

    stored = await provider.put_object(
        ref,
        b"hello",
        content_type="text/plain",
        metadata={"purpose": "test"},
    )

    assert stored.ref == ref
    assert stored.size_bytes == 5
    assert stored.content_type == "text/plain"
    assert stored.metadata == {"purpose": "test"}
    assert await provider.get_object(ref) == b"hello"
    root = (
        tmp_path / "platform_private" if platform else tmp_path / "private-ws" / str(WORKSPACE_ID)
    )
    assert provider.filesystem_path(ref) == root / ref.key
    assert stored.public_url is None
    assert stored.cache_control is None

    stat = await provider.stat_object(ref)
    assert stat is not None
    assert stat.etag == stored.etag

    assert await provider.delete_object(ref) is True
    assert await provider.stat_object(ref) is None
    assert await provider.delete_object(ref) is False


@pytest.mark.parametrize("platform", [True])
async def test_local_promotion_is_create_only_and_preserves_validated_bytes(
    tmp_path, platform: bool
) -> None:
    provider = _provider(tmp_path)
    source = make_storage_object_ref(
        StorageBucket.PLATFORM_PRIVATE if platform else StorageBucket.PRIVATE,
        "platform/uploads/source.txt" if platform else _private_key("uploads/source.txt"),
    )
    destination = make_storage_object_ref(
        StorageBucket.PLATFORM_PRIVATE if platform else StorageBucket.PRIVATE,
        "platform/files/final.txt" if platform else _private_key("files/final.txt"),
    )
    source_stored = await provider.put_object(source, b"validated", content_type="text/plain")

    promoted = await provider.promote_object(
        source,
        destination,
        expected_source_etag=source_stored.etag,
    )

    assert promoted.content_type == "text/plain"
    assert await provider.get_object(destination) == b"validated"
    await provider.put_object(source, b"changed", content_type="text/plain")
    with pytest.raises(StoragePreconditionError):
        await provider.promote_object(
            source,
            destination,
            expected_source_etag=(await provider.stat_object(source)).etag,  # type: ignore[union-attr]
        )
    assert await provider.get_object(destination) == b"validated"


async def test_interrupted_storage_write_removes_partial_object(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = _provider(tmp_path)
    ref = make_storage_object_ref(StorageBucket.PRIVATE, _private_key("files/partial.txt"))
    original_put = provider.put_object

    async def fail_after_write(*args, **kwargs):
        await original_put(*args, **kwargs)
        raise RuntimeError("write interrupted")

    monkeypatch.setattr(provider, "put_object", fail_after_write)

    with pytest.raises(RuntimeError, match="write interrupted"):
        await put_new_object_with_cleanup(provider, ref, b"partial", content_type="text/plain")

    assert await provider.stat_object(ref) is None


async def test_local_provider_signed_upload_signature_binds_content_type(tmp_path) -> None:
    provider = _provider(tmp_path)
    ref = make_storage_object_ref(StorageBucket.PRIVATE, _private_key("output.txt"))

    signed = await provider.create_signed_upload(
        ref,
        content_type="text/plain",
        expected_size_bytes=4,
        expires_in=timedelta(minutes=5),
    )
    parsed = urlsplit(signed.url)
    query = parse_qs(parsed.query)

    assert parsed.path == f"/api/v1/storage/upload/private/{_private_key('output.txt')}"
    assert provider.verify_signature(
        action="upload",
        ref=ref,
        expires=int(query["expires"][0]),
        signature=query["sig"][0],
        content_type="text/plain",
        expected_size_bytes=4,
    )
    assert not provider.verify_signature(
        action="upload",
        ref=ref,
        expires=int(query["expires"][0]),
        signature=query["sig"][0],
        expected_size_bytes=4,
        content_type="application/json",
    )


async def test_object_key_validation_rejects_traversal() -> None:
    for bad_key in ("../secret.txt", "safe/../secret.txt", "/absolute.txt", "safe//name.txt"):
        with pytest.raises(StorageValidationError):
            validate_object_key(bad_key)

        with pytest.raises(StorageValidationError):
            make_storage_object_ref(StorageBucket.PRIVATE, bad_key)


@pytest.mark.parametrize(
    ("bucket", "key"),
    [
        (StorageBucket.PLATFORM_PRIVATE, _private_key("files/report.txt")),
        (StorageBucket.PLATFORM_PRIVATE, "platform-other/files/report.txt"),
        (StorageBucket.PRIVATE, "platform/files/report.txt"),
    ],
)
async def test_platform_local_namespace_substitution_fails_closed(
    tmp_path,
    bucket: StorageBucket,
    key: str,
) -> None:
    provider = _provider(tmp_path)
    ref = make_storage_object_ref(bucket, key)
    with pytest.raises(StorageValidationError):
        await provider.put_object(ref, b"blocked")
    with pytest.raises(StorageValidationError):
        await provider.get_object(ref)
    with pytest.raises(StorageValidationError):
        await provider.stat_object(ref)
    with pytest.raises(StorageValidationError):
        await provider.delete_object(ref)
    with pytest.raises(StorageValidationError):
        _chunks = [chunk async for chunk in provider.stream_object(ref)]
    with pytest.raises(StorageValidationError):
        await provider.create_signed_upload(
            ref,
            content_type="text/plain",
            expected_size_bytes=4,
            expires_in=timedelta(minutes=5),
        )
    with pytest.raises(StorageValidationError):
        await provider.create_signed_download(ref, expires_in=timedelta(minutes=5))
