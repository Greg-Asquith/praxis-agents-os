# apps/api/tests/services/storage/test_local_provider.py

"""Local filesystem storage provider tests."""

from datetime import timedelta
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest

from services.storage.domain import StorageBucket, make_storage_object_ref
from services.storage.errors import StorageProviderUnavailableError, StorageValidationError
from services.storage.factory import get_storage_provider
from services.storage.paths import validate_object_key
from services.storage.providers.local import LocalStorageProvider
from services.storage.providers.unavailable import UnavailableStorageProvider
from tests.support.storage import reset_storage_provider_cache

pytestmark = pytest.mark.asyncio


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
    ref = make_storage_object_ref(StorageBucket.PRIVATE, "workspaces/ws_1/files/hello.txt")

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

    stat = await provider.stat_object(ref)
    assert stat is not None
    assert stat.etag == stored.etag

    assert await provider.delete_object(ref) is True
    assert await provider.stat_object(ref) is None
    assert await provider.delete_object(ref) is False


async def test_local_provider_builds_public_url(tmp_path) -> None:
    provider = _provider(tmp_path)
    ref = make_storage_object_ref(StorageBucket.PUBLIC, "users/u_1/avatar/me.png")

    stored = await provider.put_object(ref, b"png", content_type="image/png")

    assert stored.public_url == "http://testserver/api/v1/storage/public/users/u_1/avatar/me.png"
    assert stored.cache_control == "public, max-age=60"
    assert not (tmp_path / "public" / "users" / "u_1" / "avatar" / "me.png.metadata.json").exists()
    assert (tmp_path / ".metadata" / "public" / "users" / "u_1" / "avatar" / "me.png.metadata.json").is_file()


async def test_local_provider_stat_without_metadata_does_not_read_object_bytes(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = _provider(tmp_path)
    ref = make_storage_object_ref(StorageBucket.PRIVATE, "runs/run_1/lost-sidecar.txt")
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
    ref = make_storage_object_ref(StorageBucket.PRIVATE, "runs/run_1/output.txt")

    signed = await provider.create_signed_upload(
        ref,
        content_type="text/plain",
        expires_in=timedelta(minutes=5),
    )
    parsed = urlsplit(signed.url)
    query = parse_qs(parsed.query)

    assert parsed.path == "/api/v1/storage/upload/private/runs/run_1/output.txt"
    assert provider.verify_signature(
        action="upload",
        ref=ref,
        expires=int(query["expires"][0]),
        signature=query["sig"][0],
        content_type="text/plain",
    )
    assert not provider.verify_signature(
        action="upload",
        ref=ref,
        expires=int(query["expires"][0]),
        signature=query["sig"][0],
        content_type="application/json",
    )


async def test_object_key_validation_rejects_traversal() -> None:
    for bad_key in ("../secret.txt", "safe/../secret.txt", "/absolute.txt", "safe//name.txt"):
        with pytest.raises(StorageValidationError):
            validate_object_key(bad_key)

        with pytest.raises(StorageValidationError):
            make_storage_object_ref(StorageBucket.PRIVATE, bad_key)


async def test_cloud_provider_factory_returns_explicit_unavailable_stub(monkeypatch) -> None:
    from core.settings import settings

    monkeypatch.setattr(settings, "STORAGE_PROVIDER", "s3")
    reset_storage_provider_cache()
    try:
        provider = get_storage_provider()

        assert isinstance(provider, UnavailableStorageProvider)
        with pytest.raises(StorageProviderUnavailableError):
            await provider.stat_object(
                make_storage_object_ref(StorageBucket.PRIVATE, "workspaces/ws_1/file.txt")
            )
    finally:
        reset_storage_provider_cache()
