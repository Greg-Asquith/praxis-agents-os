import asyncio
import os
from contextlib import suppress

import pytest

from services.agents.runtime.code_mode.executor import MontyExecutor


def _executor(
    *,
    timeout_seconds: float = 1,
    output_max_chars: int = 20,
) -> MontyExecutor:
    return MontyExecutor(
        pool_size=1,
        timeout_seconds=timeout_seconds,
        checkout_timeout_seconds=0.2,
        request_timeout_seconds=max(timeout_seconds + 0.5, 1),
        output_max_chars=output_max_chars,
        memory_max_bytes=64 * 1024 * 1024,
        max_recursion_depth=100,
        gc_interval=1_000,
    )


async def test_executor_is_one_shot_and_bounds_print_output() -> None:
    executor = _executor(output_max_chars=5)
    try:
        first = await executor.execute("value = 40\nprint('abcdef')\nvalue + 2", external_lookup={})
        second = await executor.execute(
            "try:\n    value\nexcept NameError:\n    result = False\nresult",
            external_lookup={},
        )
    finally:
        await executor.close()

    assert first.result == 42
    assert first.output == "abcde"
    assert first.output_truncated is True
    assert second.result is False


async def test_cancellation_replaces_worker_and_close_stops_pool() -> None:
    executor = _executor(timeout_seconds=5)
    task = asyncio.create_task(executor.execute("while True:\n    pass", external_lookup={}))
    try:
        await asyncio.sleep(0.05)
        [original_pid] = executor._active_worker_pids
        pool = executor._pool
        assert pool is not None
        async with pool.checkout() as queued_session:
            pytest.fail(f"unexpected checkout while script active: {queued_session.worker_pid}")
    except TimeoutError:
        pass
    finally:
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task

    pool = executor._pool
    assert pool is not None
    async with pool.checkout() as replacement:
        replacement_pid = replacement.worker_pid
        assert await replacement.feed_run("42") == 42

    await executor.close()
    assert replacement_pid is not None
    assert replacement_pid != original_pid
    assert executor._active_worker_pids == set()
    with pytest.raises(ProcessLookupError):
        os.kill(replacement_pid, 0)


async def test_wall_clock_timeout_covers_host_dispatch() -> None:
    executor = _executor(timeout_seconds=0.03)

    async def blocked() -> int:
        await asyncio.Event().wait()
        return 42

    try:
        with pytest.raises(TimeoutError):
            await executor.execute("await blocked()", external_lookup={"blocked": blocked})
        recovered = await executor.execute("42", external_lookup={})
    finally:
        await executor.close()

    assert recovered.result == 42
