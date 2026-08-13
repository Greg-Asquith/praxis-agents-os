import asyncio
from dataclasses import dataclass
from importlib.metadata import version
from typing import Any

import pytest
from pydantic_monty import (
    AsyncFunctionSnapshot,
    AsyncFutureSnapshot,
    AsyncMonty,
    ExternalSettledResult,
    MontyComplete,
    MontyConversionError,
    MontyCrashedError,
    MontyRuntimeError,
    ResourceLimits,
)


@dataclass
class ProbeRecord:
    value: int


async def _run_snapshot_automatically(snapshot: Any) -> MontyComplete:
    while not isinstance(snapshot, MontyComplete):
        snapshot = await snapshot.resume_auto()
    return snapshot


async def _settle_async_external_call(
    snapshot: AsyncFunctionSnapshot,
    result: ExternalSettledResult,
) -> Any:
    future_snapshot = await snapshot.resume({"future": ...})
    assert isinstance(future_snapshot, AsyncFutureSnapshot)
    assert future_snapshot.pending_call_ids == [snapshot.call_id]
    return await future_snapshot.resume({snapshot.call_id: result})


def _assert_runtime_error(error: MontyRuntimeError, expected_type: type[BaseException]) -> None:
    assert isinstance(error.exception(), expected_type)


def test_exact_monty_packages_are_installed() -> None:
    assert version("pydantic-monty") == "0.0.21"
    assert version("pydantic-monty-client") == "0.0.21"
    assert version("pydantic-monty-runtime") == "0.0.21"


async def test_feed_run_calls_sync_and_async_external_functions() -> None:
    def add(left: int, right: int) -> int:
        return left + right

    async def multiply(left: int, right: int) -> int:
        await asyncio.sleep(0)
        return left * right

    async with AsyncMonty() as pool, pool.checkout() as session:
        result = await session.feed_run(
            "(add(2, 3), await multiply(4, 5))",
            external_lookup={"add": add, "multiply": multiply},
        )

    assert result == (5, 20)


@pytest.mark.parametrize(
    ("external_result", "expected"),
    [
        ({"return_value": 42}, 42),
        ({"exception": ValueError("instance failure")}, ("ValueError", "instance failure")),
        ({"exc_type": "ValueError", "message": "data failure"}, ("ValueError", "data failure")),
    ],
)
async def test_manual_driver_resume_contract(
    external_result: ExternalSettledResult,
    expected: object,
) -> None:
    async def tool() -> None:
        raise AssertionError("manual resume must not call external_lookup")

    code = """
result = None
try:
    result = await tool()
except ValueError as exc:
    result = (type(exc).__name__, str(exc))
result
"""
    async with AsyncMonty() as pool, pool.checkout() as session:
        snapshot = await session.feed_start(code, external_lookup={"tool": tool})

        assert isinstance(snapshot, AsyncFunctionSnapshot)
        assert snapshot.function_name == "tool"
        assert snapshot.call_id == 0
        assert snapshot.args == ()
        assert snapshot.kwargs == {}

        completed = await _settle_async_external_call(snapshot, external_result)

    assert isinstance(completed, MontyComplete)
    assert completed.output == expected


async def test_suspended_snapshot_round_trips_across_pool_instances() -> None:
    async def original_tool(value: int) -> int:
        raise AssertionError("snapshot load must rebind external_lookup")

    async def rebound_tool(value: int) -> int:
        return value * 2

    async with AsyncMonty() as first_pool, first_pool.checkout() as first_session:
        snapshot = await first_session.feed_start(
            "await tool(21)",
            external_lookup={"tool": original_tool},
        )
        assert isinstance(snapshot, AsyncFunctionSnapshot)
        snapshot_bytes = snapshot.dump()

    async with AsyncMonty() as second_pool, second_pool.checkout() as second_session:
        restored = await second_session.load_snapshot(
            snapshot_bytes,
            external_lookup={"tool": rebound_tool},
        )
        assert isinstance(restored, AsyncFunctionSnapshot)
        assert restored.function_name == "tool"
        assert restored.args == (21,)

        completed = await _run_snapshot_automatically(restored)

    assert completed.output == 42


async def test_external_function_exception_is_catchable_in_script() -> None:
    async def fail() -> None:
        raise LookupError("host failure")

    code = """
result = None
try:
    await fail()
except LookupError as exc:
    result = str(exc)
result
"""
    async with AsyncMonty() as pool, pool.checkout() as session:
        result = await session.feed_run(code, external_lookup={"fail": fail})

    assert result == "host failure"


async def test_request_timeout_kills_and_replaces_worker() -> None:
    async with AsyncMonty(
        min_processes=1,
        max_processes=1,
        request_timeout=0.05,
    ) as pool:
        async with pool.checkout() as session:
            original_pid = session.worker_pid
            with pytest.raises(MontyCrashedError) as exc_info:
                await session.feed_run("while True:\n    pass")

        assert exc_info.value.timed_out is True
        async with pool.checkout() as replacement_session:
            replacement_pid = replacement_session.worker_pid
            assert await replacement_session.feed_run("6 * 7") == 42

    assert original_pid is not None
    assert replacement_pid is not None
    assert replacement_pid != original_pid


async def test_checkout_timeout_bounds_pool_wait() -> None:
    pool = AsyncMonty(
        min_processes=1,
        max_processes=1,
        checkout_timeout=0.01,
    )
    async with pool, pool.checkout():
        with pytest.raises(TimeoutError):
            async with pool.checkout():
                pytest.fail("a second checkout must not exceed pool capacity")


async def test_language_surface_and_stdlib_allowlist() -> None:
    allowed_modules = (
        "asyncio",
        "collections",
        "dataclasses",
        "datetime",
        "itertools",
        "json",
        "math",
        "os",
        "pathlib",
        "re",
        "sys",
        "typing",
        "unicodedata",
    )
    imports = "\n".join(f"import {module}" for module in allowed_modules)
    code = f"""
{imports}

def decorate(cls):
    return cls

@decorate
class Counter:
    def __init__(self, value: int):
        self.value = value

    async def doubled(self) -> int:
        return self.value * 2

counter = Counter(21)
await counter.doubled()
"""
    async with AsyncMonty() as pool:
        async with pool.checkout(type_check=True) as session:
            assert await session.feed_run(code) == 42

        async with pool.checkout() as session:
            with pytest.raises(MontyRuntimeError) as exc_info:
                await session.feed_run("import sqlalchemy")

    _assert_runtime_error(exc_info.value, ModuleNotFoundError)


@pytest.mark.parametrize(
    ("code", "expected_type"),
    [
        ("import os\nos.getenv('HOME')", RuntimeError),
        ("import datetime\ndatetime.datetime.now()", RuntimeError),
        ("import pathlib\npathlib.Path('/etc/passwd').read_text()", PermissionError),
        ("import socket", ModuleNotFoundError),
    ],
)
async def test_host_access_is_unavailable_without_handlers(
    code: str,
    expected_type: type[BaseException],
) -> None:
    async with AsyncMonty() as pool, pool.checkout() as session:
        with pytest.raises(MontyRuntimeError) as exc_info:
            await session.feed_run(code)

    _assert_runtime_error(exc_info.value, expected_type)


@pytest.mark.parametrize(
    ("limits", "code", "expected_type"),
    [
        ({"max_duration_secs": 0.01}, "while True:\n    pass", TimeoutError),
        (
            {"max_memory": 10_000},
            "try:\n    [value for value in range(100_000)]\nexcept MemoryError:\n    'caught'",
            MemoryError,
        ),
        (
            {"max_recursion_depth": 10},
            "def recurse(value):\n    return 0 if value == 0 else recurse(value - 1)\nrecurse(100)",
            RecursionError,
        ),
    ],
)
async def test_resource_limit_semantics(
    limits: ResourceLimits,
    code: str,
    expected_type: type[BaseException],
) -> None:
    assert ResourceLimits.__optional_keys__ == {
        "gc_interval",
        "max_duration_secs",
        "max_memory",
        "max_recursion_depth",
    }
    assert ResourceLimits.__required_keys__ == set()

    pool = AsyncMonty(min_processes=1, max_processes=1)
    async with pool:
        async with pool.checkout(limits=limits) as session:
            worker_pid = session.worker_pid
            with pytest.raises(MontyRuntimeError) as exc_info:
                await session.feed_run(code)

            _assert_runtime_error(exc_info.value, expected_type)
            assert session.worker_pid == worker_pid

        async with pool.checkout() as recovered_session:
            assert recovered_session.worker_pid == worker_pid
            assert await recovered_session.feed_run("40 + 2") == 42


async def test_integrated_manual_driver_retains_pre_call_snapshot() -> None:
    dispatch_started = asyncio.Event()
    release_dispatch = asyncio.Event()

    async def dispatch(value: int, *, increment: int) -> int:
        dispatch_started.set()
        await release_dispatch.wait()
        return value + increment

    async with AsyncMonty() as pool, pool.checkout() as session:
        snapshot = await session.feed_start(
            "await dispatch(40, increment=2)",
            external_lookup={"dispatch": dispatch},
        )
        assert isinstance(snapshot, AsyncFunctionSnapshot)

        dispatch_task = asyncio.create_task(dispatch(*snapshot.args, **snapshot.kwargs))
        await dispatch_started.wait()
        pre_call_snapshot = snapshot.dump()
        assert pre_call_snapshot

        release_dispatch.set()
        dispatch_result = await dispatch_task
        completed = await _settle_async_external_call(
            snapshot,
            {"return_value": dispatch_result},
        )
        assert isinstance(completed, MontyComplete)
        assert completed.output == 42

    async with AsyncMonty() as restored_pool, restored_pool.checkout() as restored_session:
        restored = await restored_session.load_snapshot(
            pre_call_snapshot,
            external_lookup={"dispatch": dispatch},
        )
        assert isinstance(restored, AsyncFunctionSnapshot)
        with pytest.raises(MontyRuntimeError) as exc_info:
            await _settle_async_external_call(
                restored,
                {"exc_type": "PermissionError", "message": "approval denied"},
            )

    _assert_runtime_error(exc_info.value, PermissionError)


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (b"binary", b"binary"),
        ((1, 2), (1, 2)),
        ({1, 2}, {1, 2}),
        (ProbeRecord(value=42), ProbeRecord(value=42)),
    ],
)
async def test_supported_boundary_values(value: object, expected: object) -> None:
    async with AsyncMonty() as pool, pool.checkout(dataclass_registry=[ProbeRecord]) as session:
        assert await session.feed_run("value", inputs={"value": value}) == expected


@pytest.mark.parametrize("value", [bytearray(b"binary"), complex(1, 2)])
async def test_unsupported_boundary_values(value: object) -> None:
    async with AsyncMonty() as pool, pool.checkout(dataclass_registry=[ProbeRecord]) as session:
        with pytest.raises(MontyConversionError):
            await session.feed_run("value", inputs={"value": value})
