# apps/api/services/agents/runtime/cancellation.py

"""Cancellation markers for user-requested agent run stops."""

import asyncio
from typing import Any
from uuid import UUID
from weakref import WeakSet

AGENT_RUN_CANCEL_REQUEST = "agent_run_cancel_requested"
_agent_run_cancel_tasks: WeakSet[asyncio.Task[Any]] = WeakSet()
_agent_run_cancel_ids: set[UUID] = set()


def request_agent_run_task_cancel(task: asyncio.Task[Any], *, run_id: UUID) -> None:
    """Cancel a task with the marker used for cooperative run cancellation."""
    _agent_run_cancel_tasks.add(task)
    _agent_run_cancel_ids.add(run_id)
    task.add_done_callback(lambda _task: clear_agent_run_cancel_request(run_id))
    task.cancel(AGENT_RUN_CANCEL_REQUEST)


def is_agent_run_cancel_request(
    exc: asyncio.CancelledError,
    *,
    run_id: UUID,
) -> bool:
    """Return whether ``exc`` came from the run cancellation path."""
    if AGENT_RUN_CANCEL_REQUEST in exc.args:
        return True
    if run_id in _agent_run_cancel_ids:
        return True
    current_task = asyncio.current_task()
    return current_task is not None and current_task in _agent_run_cancel_tasks


def clear_agent_run_cancel_request(run_id: UUID) -> None:
    """Forget the run-scoped cancellation marker after the run exits."""
    _agent_run_cancel_ids.discard(run_id)
