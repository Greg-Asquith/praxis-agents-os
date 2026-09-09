# apps/api/services/agents/runtime/run_manager.py

"""Strong-reference registry for detached agent turn workers."""

import asyncio
import logging
from collections.abc import Coroutine
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from core.settings import settings
from services.agents.runtime.cancellation import request_agent_run_task_cancel
from services.agents.runtime.execution_control import (
    ExecutionControl,
    ExecutionPhase,
    InterruptionReason,
)
from services.agents.runtime.heartbeat import (
    heartbeat_agent_run_lease,
    stop_agent_run_heartbeat,
)
from services.agents.runtime.sinks import EventSink
from services.agents.runtime.stream_protocol import RunStatusEvent

logger = logging.getLogger(__name__)


@dataclass
class _RunTaskState:
    """Own resources that need cleanup even when a task never starts."""

    worker: Coroutine[Any, Any, Any]
    sink: EventSink | None
    execution_control: ExecutionControl | None = None
    stop_reason: InterruptionReason = InterruptionReason.PROCESS_SHUTDOWN
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
        execution_control: ExecutionControl | None = None,
    ) -> asyncio.Task[Any]:
        """Create and store a task for one run until it finishes."""
        existing = self._tasks.get(run_id)
        if existing is not None and not existing.done():
            coro.close()
            raise RuntimeError(f"Agent run task already exists for run {run_id}")

        state = _RunTaskState(worker=coro, sink=sink, execution_control=execution_control)
        task = asyncio.create_task(
            self._run_with_turn_slot(
                run_id,
                state,
                execution_control=execution_control,
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
        execution_control: ExecutionControl | None,
    ) -> Any:
        state.started = True
        acquired = False
        worker_started = False
        heartbeat_stop: asyncio.Event | None = None
        heartbeat_task: asyncio.Task[None] | None = None
        try:
            queued = self._turn_slots.locked()
            if queued and state.sink is not None:
                await state.sink.emit(RunStatusEvent(status="queued"))
            if queued and execution_control is not None:
                heartbeat_stop = asyncio.Event()
                heartbeat_task = asyncio.create_task(
                    heartbeat_agent_run_lease(
                        execution_control=execution_control,
                        stop=heartbeat_stop,
                        cancel_target=asyncio.current_task(),
                        renew_immediately=True,
                    ),
                    name=f"agent-run-queue-heartbeat:{run_id}",
                )
            control = execution_control
            async with asyncio.timeout_at(control.deadline if control else None):
                await self._turn_slots.acquire()
            acquired = True
            await stop_agent_run_heartbeat(heartbeat_stop, heartbeat_task)
            worker_started = True
            return await state.worker
        except (TimeoutError, asyncio.CancelledError) as exc:
            if not worker_started and execution_control is not None:
                await self._settle_queued_run(execution_control, state.sink, exc)
            raise
        finally:
            if execution_control is not None:
                execution_control.phase = ExecutionPhase.RELEASED
            await stop_agent_run_heartbeat(heartbeat_stop, heartbeat_task)
            if acquired:
                self._turn_slots.release()
            state.worker.close()
            if state.sink is not None:
                await state.sink.close()

    async def _settle_queued_run(
        self,
        control: ExecutionControl | None,
        sink: EventSink | None,
        exc: TimeoutError | asyncio.CancelledError,
    ) -> None:
        if control is None or sink is None:
            return
        from services.agents.runtime.execute.bounded_finalisation import bounded_finalisation
        from services.agents.runtime.execute.finalize import (
            CANCEL_FINALIZE_TIMEOUT,
            finalize_cancelled_run,
            finalize_stopped_run,
        )

        if isinstance(exc, TimeoutError):
            reason = InterruptionReason.DURATION_EXPIRED
        else:
            try:
                reason = InterruptionReason(exc.args[0])
            except (IndexError, ValueError):
                reason = InterruptionReason.PROCESS_SHUTDOWN
        control.interrupt(reason)
        control.phase = ExecutionPhase.FINALISING
        if control.reason == InterruptionReason.REQUESTED_CANCELLATION:
            operation = finalize_cancelled_run(
                owner_instance_id=control.owner_instance_id,
                event_sink=sink,
                run_id=control.run_id,
                workspace_id=control.workspace_id,
                user_id=control.user_id,
            )
        else:
            operation = finalize_stopped_run(
                event_sink=sink,
                run_id=control.run_id,
                workspace_id=control.workspace_id,
                user_id=control.user_id,
                owner_instance_id=control.owner_instance_id,
                reason=control.reason,
            )
        await bounded_finalisation(operation, max_wait=CANCEL_FINALIZE_TIMEOUT)

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
            state.stop_reason = InterruptionReason.REQUESTED_CANCELLATION
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
            from services.agents.runtime.execute.finalize import CANCEL_FINALIZE_TIMEOUT

            for task in pending:
                task.cancel(InterruptionReason.PROCESS_SHUTDOWN.value)
            stopped, unfinished = await asyncio.wait(pending, timeout=3 * CANCEL_FINALIZE_TIMEOUT)
            for task in stopped:
                self._log_task_exception(task)
            if unfinished:
                logger.error(
                    "Agent run shutdown cleanup remains supervised",
                    extra={"pending_count": len(unfinished)},
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
            self._cleanup_before_start(state),
            name=f"agent-run-prestart-cleanup:{run_id}",
        )
        self._cleanup_tasks.add(cleanup_task)
        cleanup_task.add_done_callback(self._finish_cleanup)

    async def _cleanup_before_start(self, state: _RunTaskState) -> None:
        try:
            await self._settle_queued_run(
                state.execution_control,
                state.sink,
                asyncio.CancelledError(state.stop_reason.value),
            )
        finally:
            if state.execution_control is not None:
                state.execution_control.phase = ExecutionPhase.RELEASED
            if state.sink is not None:
                await state.sink.close()

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
