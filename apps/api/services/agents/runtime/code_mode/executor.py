# apps/api/services/agents/runtime/code_mode/executor.py

"""Process-local Monty pool and one-shot sandbox execution."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field, replace
from typing import Any

from pydantic_ai import ApprovalRequired, CallDeferred
from pydantic_monty import (
    AsyncFunctionSnapshot,
    AsyncFutureSnapshot,
    AsyncMonty,
    ExternalSettledResult,
    MontyComplete,
    OSPolicy,
    ResourceLimits,
)

from core.settings import settings

ExternalFunction = Callable[..., Awaitable[Any]]
PendingSettlement = Callable[[], Awaitable[ExternalSettledResult]]

# Sleeps return at once so a script cannot hold a pool worker idle.
_OS_POLICY: OSPolicy = {"sleep": "zero"}


@dataclass(frozen=True)
class ScriptExecution:
    """A completed one-shot script and its independently bounded print output."""

    result: Any
    output: str
    output_truncated: bool


@dataclass(frozen=True)
class QueuedCall:
    """An external call the script has made that the host hasn't started."""

    call_id: int
    function_name: str
    args: tuple[Any, ...] = ()
    kwargs: dict[str, Any] = field(default_factory=dict)
    # Set when a restored call can't be rebuilt; the script receives this failure.
    error: str | None = None


@dataclass(frozen=True)
class ScriptSuspension:
    """An interpreter snapshot waiting on one nested approval, plus calls not yet started."""

    snapshot: bytes
    pending_call_id: int
    queued_calls: tuple[QueuedCall, ...]
    approval: ApprovalRequired | CallDeferred
    output: str
    output_truncated: bool


@dataclass
class _BoundedOutput:
    max_chars: int
    _chunks: list[str] = field(default_factory=list)
    _chars: int = 0
    truncated: bool = False

    def write(self, _stream: str, text: str) -> None:
        remaining = self.max_chars - self._chars
        if remaining <= 0:
            self.truncated = True
            return
        self._chunks.append(text[:remaining])
        self._chars += min(len(text), remaining)
        self.truncated = self.truncated or len(text) > remaining

    def value(self) -> str:
        return "".join(self._chunks)


class MontyExecutor:
    """Own one lazily-started Monty worker pool for an application process."""

    def __init__(
        self,
        *,
        pool_size: int,
        timeout_seconds: float,
        checkout_timeout_seconds: float,
        request_timeout_seconds: float,
        output_max_chars: int,
        memory_max_bytes: int,
        max_recursion_depth: int,
        gc_interval: int,
    ) -> None:
        self._pool_size = pool_size
        self._timeout_seconds = timeout_seconds
        self._checkout_timeout_seconds = checkout_timeout_seconds
        self._request_timeout_seconds = request_timeout_seconds
        self._output_max_chars = output_max_chars
        self._limits: ResourceLimits = {
            "max_feed_duration_secs": timeout_seconds,
            "max_memory": memory_max_bytes,
            "max_recursion_depth": max_recursion_depth,
            "gc_interval": gc_interval,
        }
        self._pool: AsyncMonty | None = None
        self._pool_lock = asyncio.Lock()
        self._active_worker_pids: set[int] = set()

    @classmethod
    def from_settings(cls) -> MontyExecutor:
        """Build an executor from the validated process settings."""
        return cls(
            pool_size=settings.AGENT_CODE_MODE_POOL_SIZE,
            timeout_seconds=settings.AGENT_CODE_MODE_TIMEOUT_SECONDS,
            checkout_timeout_seconds=settings.AGENT_CODE_MODE_CHECKOUT_TIMEOUT_SECONDS,
            request_timeout_seconds=settings.AGENT_CODE_MODE_REQUEST_TIMEOUT_SECONDS,
            output_max_chars=settings.AGENT_CODE_MODE_OUTPUT_MAX_CHARS,
            memory_max_bytes=settings.AGENT_CODE_MODE_MEMORY_MAX_BYTES,
            max_recursion_depth=settings.AGENT_CODE_MODE_MAX_RECURSION_DEPTH,
            gc_interval=settings.AGENT_CODE_MODE_GC_INTERVAL,
        )

    async def execute(
        self,
        code: str,
        *,
        external_lookup: Mapping[str, ExternalFunction],
        timeout_seconds: float | None = None,
    ) -> ScriptExecution | ScriptSuspension:
        """Run one script with no persisted interpreter state or ambient host access."""
        pool = await self._get_pool()
        output = _BoundedOutput(self._output_max_chars)
        async with asyncio.timeout(timeout_seconds or self._timeout_seconds):
            async with pool.checkout(limits=self._limits, os_policy=_OS_POLICY) as session:
                worker_pid = session.worker_pid
                if worker_pid is not None:
                    self._active_worker_pids.add(worker_pid)
                try:
                    snapshot = await session.feed_start(
                        code,
                        external_lookup=dict(external_lookup),
                        print_callback=output.write,
                    )
                    completed = await _drive_script(snapshot, external_lookup=external_lookup)
                finally:
                    if worker_pid is not None:
                        self._active_worker_pids.discard(worker_pid)
        if isinstance(completed, ScriptSuspension):
            return replace(completed, output=output.value(), output_truncated=output.truncated)
        return ScriptExecution(
            result=completed.output, output=output.value(), output_truncated=output.truncated
        )

    async def resume(
        self,
        snapshot_bytes: bytes,
        *,
        pending_call_id: int,
        queued_calls: tuple[QueuedCall, ...],
        external_lookup: Mapping[str, ExternalFunction],
        settle_pending: PendingSettlement,
        timeout_seconds: float,
        prior_output: str = "",
        prior_output_truncated: bool = False,
    ) -> ScriptExecution | ScriptSuspension:
        """Restore a trusted paused interpreter and settle its pending nested call once."""
        pool = await self._get_pool()
        output = _BoundedOutput(max(0, self._output_max_chars - len(prior_output)))
        output.truncated = prior_output_truncated
        # Restored snapshots keep their saved limits, so the host timeout bounds remaining time.
        async with asyncio.timeout(timeout_seconds):
            async with pool.checkout(
                limits=self._limits,
                os_policy=_OS_POLICY,
            ) as session:
                restored = await session.load_snapshot(
                    snapshot_bytes,
                    external_lookup=dict(external_lookup),
                    print_callback=output.write,
                )
                if not isinstance(restored, AsyncFutureSnapshot):
                    raise TypeError("Code Mode snapshot is not waiting on an external call")
                queued = {call.call_id: call for call in queued_calls}
                if set(restored.pending_call_ids) != {pending_call_id, *queued}:
                    raise TypeError("Code Mode snapshot does not match its saved calls")
                initial_result = await settle_pending()
                snapshot = await restored.resume({pending_call_id: initial_result})
                completed = await _drive_script(
                    snapshot, external_lookup=external_lookup, queued=queued
                )
        if isinstance(completed, ScriptSuspension):
            return replace(
                completed,
                output=prior_output + output.value(),
                output_truncated=output.truncated,
            )
        return ScriptExecution(
            result=completed.output,
            output=prior_output + output.value(),
            output_truncated=output.truncated,
        )

    async def close(self) -> None:
        """Stop every Monty worker owned by this executor."""
        async with self._pool_lock:
            pool, self._pool = self._pool, None
        if pool is not None:
            await pool.__aexit__(None, None, None)

    async def _get_pool(self) -> AsyncMonty:
        async with self._pool_lock:
            if self._pool is None:
                pool = AsyncMonty(
                    min_processes=self._pool_size,
                    max_processes=self._pool_size,
                    checkout_timeout=self._checkout_timeout_seconds,
                    request_timeout=self._request_timeout_seconds,
                )
                await pool.__aenter__()
                self._pool = pool
            return self._pool


async def _drive_script(
    snapshot: Any,
    *,
    external_lookup: Mapping[str, ExternalFunction],
    queued: dict[int, QueuedCall] | None = None,
) -> MontyComplete | ScriptSuspension:
    """Run each external call only when the script awaits it, one at a time.

    Calls are queued when the script makes them and started only from a future
    snapshot. When a call needs approval, that future snapshot is the resume
    point: every other call it waits on is queued and hasn't started, so resume
    neither repeats nor loses an effect.
    """
    queued = dict(queued or {})
    while not isinstance(snapshot, MontyComplete):
        if isinstance(snapshot, AsyncFunctionSnapshot):
            if snapshot.function_name not in external_lookup:
                snapshot = await snapshot.resume(
                    {
                        "exc_type": "NameError",
                        "message": f"Unknown sandbox function: {snapshot.function_name}",
                    }
                )
                continue
            queued[snapshot.call_id] = QueuedCall(
                call_id=snapshot.call_id,
                function_name=str(snapshot.function_name),
                args=tuple(snapshot.args),
                kwargs=dict(snapshot.kwargs),
            )
            snapshot = await snapshot.resume({"future": ...})
            continue

        if isinstance(snapshot, AsyncFutureSnapshot):
            call_id = next(
                (call_id for call_id in snapshot.pending_call_ids if call_id in queued),
                None,
            )
            if call_id is None:
                raise RuntimeError("Monty requested an unknown pending external call")
            call = queued.pop(call_id)
            try:
                settled = await _run_queued_call(call, external_lookup=external_lookup)
            except (ApprovalRequired, CallDeferred) as exc:
                return ScriptSuspension(
                    snapshot=snapshot.dump(),
                    pending_call_id=call_id,
                    queued_calls=tuple(queued.values()),
                    approval=exc,
                    output="",
                    output_truncated=False,
                )
            snapshot = await snapshot.resume({call_id: settled})
            continue

        snapshot = await snapshot.resume_auto()
    return snapshot


async def _run_queued_call(
    call: QueuedCall,
    *,
    external_lookup: Mapping[str, ExternalFunction],
) -> ExternalSettledResult:
    if call.error is not None:
        return {"exc_type": "RuntimeError", "message": call.error}
    external_function = external_lookup.get(call.function_name)
    if external_function is None:
        return {
            "exc_type": "NameError",
            "message": f"Unknown sandbox function: {call.function_name}",
        }
    try:
        return {"return_value": await external_function(*call.args, **call.kwargs)}
    except (ApprovalRequired, CallDeferred):
        raise
    except Exception as exc:
        return {"exc_type": "RuntimeError", "message": str(exc)}


_default_executor: MontyExecutor | None = None
_default_executor_lock = asyncio.Lock()


async def get_code_mode_executor() -> MontyExecutor:
    """Return the process-wide executor, creating its pool only on first execution."""
    global _default_executor
    async with _default_executor_lock:
        if _default_executor is None:
            _default_executor = MontyExecutor.from_settings()
        return _default_executor


async def close_code_mode_executor() -> None:
    """Close and discard the process-wide executor."""
    global _default_executor
    async with _default_executor_lock:
        executor, _default_executor = _default_executor, None
    if executor is not None:
        await executor.close()
