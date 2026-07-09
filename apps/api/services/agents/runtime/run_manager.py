# apps/api/services/agents/runtime/run_manager.py

"""Strong-reference registry for detached agent turn workers."""

import asyncio
import logging
from collections.abc import Coroutine
from typing import Any
from uuid import UUID

from services.agents.runtime.cancellation import request_agent_run_task_cancel

logger = logging.getLogger(__name__)


class RunTaskRegistry:
    """Own in-flight agent run tasks so detached workers cannot be GC'd."""

    def __init__(self) -> None:
        self._tasks: dict[UUID, asyncio.Task[Any]] = {}

    def spawn(self, run_id: UUID, coro: Coroutine[Any, Any, Any]) -> asyncio.Task[Any]:
        """Create and store a task for one run until it finishes."""
        existing = self._tasks.get(run_id)
        if existing is not None and not existing.done():
            raise RuntimeError(f"Agent run task already exists for run {run_id}")

        task = asyncio.create_task(coro, name=f"agent-run:{run_id}")
        self._tasks[run_id] = task
        task.add_done_callback(lambda finished: self._discard(run_id, finished))
        return task

    def is_running(self, run_id: UUID) -> bool:
        task = self._tasks.get(run_id)
        return task is not None and not task.done()

    def cancel(self, run_id: UUID) -> bool:
        """Request cancellation of a process-local run task."""
        task = self._tasks.get(run_id)
        if task is None or task.done():
            return False
        request_agent_run_task_cancel(task, run_id=run_id)
        return True

    async def drain(self, *, max_wait_seconds: float | None = None) -> None:
        """Wait for currently in-flight tasks up to ``max_wait_seconds`` seconds."""
        tasks = [task for task in self._tasks.values() if not task.done()]
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
        self._log_task_exception(task)

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
