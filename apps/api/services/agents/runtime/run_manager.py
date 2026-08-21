# apps/api/services/agents/runtime/run_manager.py

"""Strong-reference registry for detached agent turn workers."""

import asyncio
import logging
from collections.abc import Coroutine
from contextlib import suppress
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from core.settings import settings
from services.agents.runtime.cancellation import request_agent_run_task_cancel
from services.agents.runtime.heartbeat import (
    agent_run_owner_instance_id,
    heartbeat_agent_run_lease,
)
from services.agents.runtime.sinks import EventSink
from services.agents.runtime.stream_protocol import RunStatusEvent

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class QueuedRunLease:
    """Identifies the tenant context needed to renew a queued run lease."""

    workspace_id: UUID
    user_id: UUID


@dataclass
class _RunTaskState:
    """Own resources that need cleanup even when a task never starts."""

    worker: Coroutine[Any, Any, Any]
    sink: EventSink | None
    started: bool = False
    prestart_cleanup_scheduled: bool = False


class RunTaskRegistry:
    """Own in-flight agent run tasks so detached workers cannot be GC'd."""

    def __init__(self, *, max_concurrent_turns: int | None = None) -> None:
        resolved_limit = (
            settings.AGENT_RUN_MAX_CONCURRENT_TURNS
            if max_concurrent_turns is None
            else max_concurrent_turns
        )
        if resolved_limit < 1:
            raise ValueError("max_concurrent_turns must be at least 1")
        self._tasks: dict[UUID, asyncio.Task[Any]] = {}
        self._task_states: dict[UUID, _RunTaskState] = {}
        self._cleanup_tasks: set[asyncio.Task[None]] = set()
        self._turn_slots = asyncio.Semaphore(resolved_limit)

    def spawn(
        self,
        run_id: UUID,
        coro: Coroutine[Any, Any, Any],
        *,
        sink: EventSink | None = None,
        queued_lease: QueuedRunLease | None = None,
    ) -> asyncio.Task[Any]:
        """Create and store a task for one run until it finishes."""
        existing = self._tasks.get(run_id)
        if existing is not None and not existing.done():
            coro.close()
            raise RuntimeError(f"Agent run task already exists for run {run_id}")

        state = _RunTaskState(worker=coro, sink=sink)
        task = asyncio.create_task(
            self._run_with_turn_slot(
                run_id,
                state,
                queued_lease=queued_lease,
            ),
            name=f"agent-run:{run_id}",
        )
        self._tasks[run_id] = task
        self._task_states[run_id] = state
        task.add_done_callback(lambda finished: self._finish(run_id, finished, state))
        return task

    async def _run_with_turn_slot(
        self,
        run_id: UUID,
        state: _RunTaskState,
        *,
        queued_lease: QueuedRunLease | None,
    ) -> Any:
        state.started = True
        acquired = False
        heartbeat_stop: asyncio.Event | None = None
        heartbeat_task: asyncio.Task[None] | None = None
        try:
            queued = self._turn_slots.locked()
            if queued and state.sink is not None:
                await state.sink.emit(RunStatusEvent(status="queued"))
            if queued and queued_lease is not None:
                heartbeat_stop = asyncio.Event()
                heartbeat_task = asyncio.create_task(
                    heartbeat_agent_run_lease(
                        run_id=run_id,
                        workspace_id=queued_lease.workspace_id,
                        user_id=queued_lease.user_id,
                        owner_instance_id=agent_run_owner_instance_id(),
                        stop=heartbeat_stop,
                        cancel_target=asyncio.current_task(),
                        renew_immediately=True,
                    ),
                    name=f"agent-run-queue-heartbeat:{run_id}",
                )
            await self._turn_slots.acquire()
            acquired = True
            if heartbeat_stop is not None:
                heartbeat_stop.set()
            if heartbeat_task is not None:
                await heartbeat_task
            return await state.worker
        finally:
            if heartbeat_stop is not None:
                heartbeat_stop.set()
            if heartbeat_task is not None and not heartbeat_task.done():
                heartbeat_task.cancel()
            if heartbeat_task is not None:
                with suppress(asyncio.CancelledError):
                    await heartbeat_task
            if acquired:
                self._turn_slots.release()
            state.worker.close()
            if state.sink is not None:
                await state.sink.close()

    def _finish(
        self,
        run_id: UUID,
        task: asyncio.Task[Any],
        state: _RunTaskState,
    ) -> None:
        if not state.started:
            self._schedule_prestart_cleanup(run_id, state)
        self._discard(run_id, task)

    def is_running(self, run_id: UUID) -> bool:
        task = self._tasks.get(run_id)
        return task is not None and not task.done()

    def cancel(self, run_id: UUID) -> bool:
        """Request cancellation of a process-local run task."""
        task = self._tasks.get(run_id)
        if task is None or task.done():
            return False
        state = self._task_states.get(run_id)
        if state is not None and not state.started:
            self._schedule_prestart_cleanup(run_id, state)
        request_agent_run_task_cancel(task, run_id=run_id)
        return True

    async def drain(self, *, max_wait_seconds: float | None = None) -> None:
        """Wait for currently in-flight tasks up to ``max_wait_seconds`` seconds."""
        tasks = [task for task in self._tasks.values() if not task.done()]
        tasks.extend(task for task in self._cleanup_tasks if not task.done())
        if not tasks:
            return

        done, pending = await asyncio.wait(tasks, timeout=max_wait_seconds)
        for task in done:
            self._log_task_exception(task)
        if pending:
            logger.warning(
                "Timed out waiting for detached agent runs",
                extra={"pending_count": len(pending)},
            )

    def _discard(self, run_id: UUID, task: asyncio.Task[Any]) -> None:
        if self._tasks.get(run_id) is task:
            self._tasks.pop(run_id, None)
            self._task_states.pop(run_id, None)
        self._log_task_exception(task)

    def _schedule_prestart_cleanup(self, run_id: UUID, state: _RunTaskState) -> None:
        if state.prestart_cleanup_scheduled:
            return
        state.prestart_cleanup_scheduled = True
        state.worker.close()
        if state.sink is None:
            return

        cleanup_task = asyncio.create_task(
            state.sink.close(),
            name=f"agent-run-prestart-cleanup:{run_id}",
        )
        self._cleanup_tasks.add(cleanup_task)
        cleanup_task.add_done_callback(self._finish_cleanup)

    def _finish_cleanup(self, task: asyncio.Task[None]) -> None:
        self._cleanup_tasks.discard(task)
        if task.cancelled():
            return
        try:
            exc = task.exception()
        except asyncio.CancelledError:
            return
        if exc is not None:
            logger.error(
                "Agent run pre-start cleanup failed",
                exc_info=(type(exc), exc, exc.__traceback__),
            )

    def _log_task_exception(self, task: asyncio.Task[Any]) -> None:
        if task.cancelled():
            return
        try:
            exc = task.exception()
        except asyncio.CancelledError:
            return
        if exc is not None:
            logger.error(
                "Detached agent run task failed",
                exc_info=(type(exc), exc, exc.__traceback__),
            )


run_task_registry = RunTaskRegistry()
