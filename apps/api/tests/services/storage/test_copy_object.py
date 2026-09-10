"""Private copy integrity, authorisation, and interruption contracts."""

import asyncio
import hashlib
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from services.storage.copy_object import MAX_COPY_BYTES, copy_object
from services.storage.domain import StorageBucket, StorageObjectRef
from services.storage.errors import StoragePreconditionError, StorageValidationError
from services.storage.providers.local import LocalStorageProvider


@pytest.fixture
async def copy_case(tmp_path):
    provider = LocalStorageProvider(
        root=tmp_path, app_base_url="http://testserver", api_prefix="/api/v1", secret_key="x" * 40
    )
    source = StorageObjectRef(bucket=StorageBucket.PRIVATE, key=f"workspaces/{uuid4()}/source")
    destination = StorageObjectRef(bucket=StorageBucket.PLATFORM_PRIVATE, key="platform/dest")
    await provider.put_object(source, b"hello", metadata={"workspace": "confidential"})
    return provider, source, destination


async def _copy(case, **overrides):
    kwargs = {
        "authorise": AsyncMock(),
        "expected_size_bytes": 5,
        "expected_sha256": hashlib.sha256(b"hello").hexdigest(),
        "content_type": "text/plain",
    }
    kwargs.update(overrides)
    return await copy_object(*case, **kwargs)


def _stages(provider):
    return list(provider.root.rglob("copy-staging/*"))


@pytest.mark.parametrize("reverse", [False, True])
async def test_copy_both_directions_and_retry(copy_case, reverse):
    provider, source, destination = copy_case
    if reverse:
        await provider.put_object(destination, b"hello", metadata={"private": "provenance"})
        await provider.delete_object(source)
        source, destination = destination, source
    case = provider, source, destination
    authorise = AsyncMock()
    first = await _copy(case, authorise=authorise)
    assert authorise.await_count == 2
    assert first.metadata == {}
    assert first.cache_control == "private, no-store"
    assert await provider.get_object(destination) == b"hello"
    assert await provider.get_object(source) == b"hello"
    await provider.delete_object(source)
    assert await _copy(case) == first
    assert not _stages(provider)


async def test_denied_copy_performs_no_storage_io(copy_case, monkeypatch):
    provider, _, _ = copy_case
    stat = AsyncMock(side_effect=AssertionError("Storage accessed before authorisation"))
    monkeypatch.setattr(provider, "stat_object", stat)
    with pytest.raises(PermissionError):
        await _copy(copy_case, authorise=AsyncMock(side_effect=PermissionError))
    stat.assert_not_awaited()


async def test_authority_withdrawn_before_promotion_cleans_stage(copy_case):
    provider, _, destination = copy_case
    with pytest.raises(PermissionError):
        await _copy(copy_case, authorise=AsyncMock(side_effect=[None, PermissionError()]))
    assert await provider.stat_object(destination) is None
    assert not _stages(provider)


@pytest.mark.parametrize("size", [-1, MAX_COPY_BYTES + 1])
async def test_invalid_limit_rejected_before_authorisation(copy_case, size):
    authorise = AsyncMock()
    with pytest.raises(StorageValidationError):
        await _copy(copy_case, expected_size_bytes=size, authorise=authorise)
    authorise.assert_not_awaited()


@pytest.mark.parametrize("change", ["public", "namespace", "same_class", "hash"])
async def test_invalid_copy_contract(copy_case, change):
    provider, source, destination = copy_case
    kwargs = {}
    if change == "public":
        destination = StorageObjectRef(bucket=StorageBucket.PUBLIC, key="public/dest")
    elif change == "namespace":
        destination = StorageObjectRef(bucket=StorageBucket.PLATFORM_PRIVATE, key=source.key)
    elif change == "same_class":
        destination = source
    else:
        kwargs["expected_sha256"] = "invalid"
    with pytest.raises(StorageValidationError):
        await _copy((provider, source, destination), **kwargs)


@pytest.mark.parametrize("content", [b"other", b"hell", b"hello!"])
async def test_stream_integrity_and_size_enforced(copy_case, monkeypatch, content):
    provider, _, destination = copy_case

    async def changed_stream(ref):
        yield content

    monkeypatch.setattr(provider, "stream_object", changed_stream)
    with pytest.raises(StoragePreconditionError):
        await _copy(copy_case)
    assert await provider.stat_object(destination) is None
    assert not _stages(provider)


async def test_existing_destination_is_not_overwritten_or_deleted(copy_case):
    provider, _, destination = copy_case
    await provider.put_object(
        destination, b"other", content_type="text/plain", cache_control="private, no-store"
    )
    with pytest.raises(StoragePreconditionError):
        await _copy(copy_case)
    assert await provider.get_object(destination) == b"other"


async def test_failure_after_staging_write_cleans_and_retries(copy_case, monkeypatch):
    provider, _, destination = copy_case
    put = provider.put_object

    async def fail_after_write(*args, **kwargs):
        await put(*args, **kwargs)
        raise RuntimeError("Lost write response")

    monkeypatch.setattr(provider, "put_object", fail_after_write)
    with pytest.raises(RuntimeError):
        await _copy(copy_case)
    assert await provider.stat_object(destination) is None
    assert not _stages(provider)
    monkeypatch.setattr(provider, "put_object", put)
    await _copy(copy_case)


async def test_lost_promotion_response_recovers_complete_destination(copy_case, monkeypatch):
    provider, _, destination = copy_case
    promote = provider.promote_object

    async def fail_after_promote(*args, **kwargs):
        await promote(*args, **kwargs)
        raise RuntimeError("Lost promotion response")

    monkeypatch.setattr(provider, "promote_object", fail_after_promote)
    await _copy(copy_case)
    assert await provider.get_object(destination) == b"hello"
    assert not _stages(provider)


async def test_cancellation_waits_for_late_write_before_cleanup(copy_case, monkeypatch):
    provider, _, destination = copy_case
    put = provider.put_object
    started = asyncio.Event()
    release = asyncio.Event()

    async def delayed_write(*args, **kwargs):
        started.set()
        await release.wait()
        return await put(*args, **kwargs)

    monkeypatch.setattr(provider, "put_object", delayed_write)
    task = asyncio.create_task(_copy(copy_case))
    await started.wait()
    task.cancel()
    await asyncio.sleep(0)
    task.cancel()
    await asyncio.sleep(0)
    assert not task.done()
    release.set()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert await provider.stat_object(destination) is None
    assert not _stages(provider)


async def test_retry_cleans_stage_left_by_delete_failure(copy_case, monkeypatch):
    provider, _, destination = copy_case
    delete = provider.delete_object
    monkeypatch.setattr(
        provider, "delete_object", AsyncMock(side_effect=RuntimeError("Unavailable"))
    )
    with pytest.raises(RuntimeError):
        await _copy(copy_case)
    assert _stages(provider)
    assert await provider.get_object(destination) == b"hello"
    monkeypatch.setattr(provider, "delete_object", delete)
    await _copy(copy_case)
    assert not _stages(provider)


async def test_cancelled_promotion_finishes_and_retry_adopts_destination(copy_case, monkeypatch):
    provider, _, destination = copy_case
    promote = provider.promote_object
    started = asyncio.Event()
    release = asyncio.Event()

    async def delayed_promotion(*args, **kwargs):
        started.set()
        await release.wait()
        return await promote(*args, **kwargs)

    monkeypatch.setattr(provider, "promote_object", delayed_promotion)
    task = asyncio.create_task(_copy(copy_case))
    await started.wait()
    task.cancel()
    await asyncio.sleep(0)
    assert not task.done()
    release.set()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert await provider.get_object(destination) == b"hello"
    assert not _stages(provider)
    monkeypatch.setattr(provider, "promote_object", AsyncMock(side_effect=AssertionError))
    assert (await _copy(copy_case)).ref == destination


async def test_retry_reuses_stage_after_failed_promotion_and_cleanup(copy_case, monkeypatch):
    provider, _, destination = copy_case
    promote, delete = provider.promote_object, provider.delete_object
    monkeypatch.setattr(provider, "promote_object", AsyncMock(side_effect=RuntimeError))
    monkeypatch.setattr(provider, "delete_object", AsyncMock(side_effect=RuntimeError))
    with pytest.raises(RuntimeError):
        await _copy(copy_case)
    assert _stages(provider)
    assert await provider.stat_object(destination) is None
    monkeypatch.setattr(provider, "promote_object", promote)
    monkeypatch.setattr(provider, "delete_object", delete)
    put = provider.put_object

    async def reject_stage_rewrite(ref, *args, **kwargs):
        assert "copy-staging/" not in ref.key
        return await put(ref, *args, **kwargs)

    monkeypatch.setattr(provider, "put_object", reject_stage_rewrite)
    await _copy(copy_case)
    assert await provider.get_object(destination) == b"hello"
    assert not _stages(provider)
