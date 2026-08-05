# apps/api/tests/services/storage/test_local_provider.py

"""Local filesystem storage provider tests."""

import asyncio
from datetime import timedelta
from pathlib import Path
from urllib.parse import parse_qs, urlsplit
from uuid import UUID

import pytest

from core.settings import settings
from services.storage.domain import StorageBucket, make_storage_object_ref
from services.storage.errors import (
    StorageNotFoundError,
    StoragePreconditionError,
    StorageValidationError,
)
from services.storage.factory import get_storage_provider
from services.storage.paths import validate_object_key
from services.storage.provider import STORAGE_STREAM_CHUNK_SIZE
from services.storage.providers.local import LocalStorageProvider
from services.storage.utils import put_new_object_with_cleanup
from tests.support.storage import reset_storage_provider_cache

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


async def test_local_provider_put_get_stat_and_delete_object(tmp_path) -> None:
    provider = _provider(tmp_path)
    ref = make_storage_object_ref(StorageBucket.PRIVATE, _private_key("files/hello.txt"))

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
    assert provider.filesystem_path(ref) == (tmp_path / "private-ws" / str(WORKSPACE_ID) / ref.key)

    stat = await provider.stat_object(ref)
    assert stat is not None
    assert stat.etag == stored.etag

    assert await provider.delete_object(ref) is True
    assert await provider.stat_object(ref) is None
    assert await provider.delete_object(ref) is False


async def test_local_promotion_is_create_only_and_preserves_validated_bytes(tmp_path) -> None:
    provider = _provider(tmp_path)
    source = make_storage_object_ref(StorageBucket.PRIVATE, _private_key("uploads/source.txt"))
    destination = make_storage_object_ref(StorageBucket.PRIVATE, _private_key("files/final.txt"))
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


async def test_cancelled_storage_write_removes_partial_object(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = _provider(tmp_path)
    ref = make_storage_object_ref(StorageBucket.PRIVATE, _private_key("files/cancelled.txt"))
    original_put = provider.put_object
    object_written = asyncio.Event()

    async def block_after_write(*args, **kwargs):
        stored = await original_put(*args, **kwargs)
        object_written.set()
        await asyncio.Event().wait()
        return stored

    monkeypatch.setattr(provider, "put_object", block_after_write)
    write = asyncio.create_task(
        put_new_object_with_cleanup(provider, ref, b"partial", content_type="text/plain")
    )
    await object_written.wait()
    write.cancel()

    with pytest.raises(asyncio.CancelledError):
        await write

    assert await provider.stat_object(ref) is None


async def test_local_provider_stream_object_chunks_and_maps_missing(tmp_path) -> None:
    provider = _provider(tmp_path)
    ref = make_storage_object_ref(StorageBucket.PRIVATE, _private_key("files/large.bin"))
    data = b"a" * (STORAGE_STREAM_CHUNK_SIZE + 17)
    await provider.put_object(ref, data, content_type="application/octet-stream")

    chunks = [chunk async for chunk in provider.stream_object(ref)]

    assert b"".join(chunks) == data
    assert len(chunks) > 1

    missing_ref = make_storage_object_ref(StorageBucket.PRIVATE, _private_key("files/missing.bin"))
    with pytest.raises(StorageNotFoundError):
        _missing = [chunk async for chunk in provider.stream_object(missing_ref)]


async def test_local_provider_builds_public_url(tmp_path) -> None:
    provider = _provider(tmp_path)
    ref = make_storage_object_ref(StorageBucket.PUBLIC, "users/u_1/avatar/me.png")

    stored = await provider.put_object(ref, b"png", content_type="image/png")

    assert stored.public_url == "http://testserver/api/v1/storage/public/users/u_1/avatar/me.png"
    assert stored.cache_control == "public, max-age=60"
    assert not (tmp_path / "public" / "users" / "u_1" / "avatar" / "me.png.metadata.json").exists()
    assert (
        tmp_path / ".metadata" / "public" / "users" / "u_1" / "avatar" / "me.png.metadata.json"
    ).is_file()


async def test_local_provider_stat_without_metadata_does_not_read_object_bytes(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = _provider(tmp_path)
    ref = make_storage_object_ref(StorageBucket.PRIVATE, _private_key("lost-sidecar.txt"))
    path = provider.filesystem_path(ref)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"metadata sidecar is missing")

    def fail_read_bytes(_self: Path) -> bytes:
        raise AssertionError("stat_object must not read object bytes")

    monkeypatch.setattr(Path, "read_bytes", fail_read_bytes)

    stat = await provider.stat_object(ref)

    assert stat is not None
    assert stat.size_bytes == 27
    assert stat.etag.startswith("local-stat-")


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


async def test_local_provider_factory_returns_local_provider(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(settings, "STORAGE_PROVIDER", "local_fs")
    monkeypatch.setattr(settings, "LOCAL_STORAGE_ROOT", str(tmp_path))
    reset_storage_provider_cache()
    try:
        provider = get_storage_provider()

        assert isinstance(provider, LocalStorageProvider)
    finally:
        reset_storage_provider_cache()
