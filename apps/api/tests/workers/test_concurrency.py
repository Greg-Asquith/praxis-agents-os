"""Process-wide worker admission tests."""

import asyncio

import pytest

from core.settings import settings
from workers.concurrency import run_worker_batch

pytestmark = pytest.mark.asyncio


async def test_parallel_batches_share_one_process_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    active = 0
    peak_active = 0
    release = asyncio.Event()
    all_slots_started = asyncio.Event()

    async def run_one() -> bool:
        nonlocal active, peak_active
        active += 1
        peak_active = max(peak_active, active)
        if active == 3:
            all_slots_started.set()
        try:
            await release.wait()
            return True
        finally:
            active -= 1

    monkeypatch.setattr(settings, "WORKER_MAX_CONCURRENT_RUNS", 3)
    first = asyncio.create_task(run_worker_batch(max_items=3, run_one=run_one))
    second = asyncio.create_task(run_worker_batch(max_items=3, run_one=run_one))
    await asyncio.wait_for(all_slots_started.wait(), timeout=1)
    await asyncio.sleep(0)

    assert peak_active == 3

    release.set()
    assert await asyncio.gather(first, second) == [3, 3]
    assert peak_active == 3


async def test_batch_waits_for_siblings_before_raising(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sibling_started = asyncio.Event()
    release_sibling = asyncio.Event()
    calls = 0

    async def run_one() -> bool:
        nonlocal calls
        calls += 1
        if calls == 1:
            await sibling_started.wait()
            raise RuntimeError("admission failed")
        sibling_started.set()
        await release_sibling.wait()
        return True

    monkeypatch.setattr(settings, "WORKER_MAX_CONCURRENT_RUNS", 2)
    batch = asyncio.create_task(run_worker_batch(max_items=2, run_one=run_one))
    await asyncio.wait_for(sibling_started.wait(), timeout=1)
    await asyncio.sleep(0)

    assert batch.done() is False

    release_sibling.set()
    with pytest.raises(ExceptionGroup, match="Worker batch execution failed"):
        await asyncio.wait_for(batch, timeout=1)


async def test_shutdown_stops_waiting_items_before_admission(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    started = asyncio.Event()
    release = asyncio.Event()
    shutdown_event = asyncio.Event()
    calls = 0

    async def run_one() -> bool:
        nonlocal calls
        calls += 1
        started.set()
        await release.wait()
        return True

    monkeypatch.setattr(settings, "WORKER_MAX_CONCURRENT_RUNS", 1)
    batch = asyncio.create_task(
        run_worker_batch(
            max_items=3,
            run_one=run_one,
            shutdown_event=shutdown_event,
        )
    )
    await asyncio.wait_for(started.wait(), timeout=1)
    shutdown_event.set()
    release.set()

    assert await asyncio.wait_for(batch, timeout=1) == 1
    assert calls == 1
