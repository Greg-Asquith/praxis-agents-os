# apps/api/services/agents/runtime/worker.py

"""Detached worker wrapper for interactive agent turns."""

import asyncio
import logging
import os
from collections.abc import Sequence
from contextlib import suppress
from uuid import UUID

from pydantic_ai import DeferredToolResults
from pydantic_ai.messages import ModelMessage
from pydantic_ai.models import Model

from core.database import configure_async_db_session, get_async_db_session_factory
from services.agent_runs.domain import RUN_STATUS_AWAITING_APPROVAL, RUN_STATUS_PENDING
from services.agents.runtime.execute_run import execute_run
from services.agents.runtime.heartbeat import heartbeat_agent_run_lease
from services.agents.runtime.sinks import EventSink

logger = logging.getLogger(__name__)


async def run_turn_worker(
    *,
    run_id: UUID,
    conversation_id: UUID,
    user_prompt: str,
    sink: EventSink,
    client_message_id: str | None = None,
    model: Model | None = None,
) -> None:
    """Run one interactive turn to completion with an independent DB session."""
    owner_instance_id = _owner_instance_id()
    heartbeat_stop = asyncio.Event()
    heartbeat_task: asyncio.Task[None] | None = None
    session_factory = get_async_db_session_factory()
    session = session_factory()

    try:
        heartbeat_task = asyncio.create_task(
            heartbeat_agent_run_lease(
                run_id=run_id,
                owner_instance_id=owner_instance_id,
                stop=heartbeat_stop,
            ),
            name=f"agent-run-heartbeat:{run_id}",
        )

        await configure_async_db_session(session)
        await execute_run(
            session,
            conversation_id=conversation_id,
            run_id=run_id,
            user_prompt=user_prompt,
            sink=sink,
            model=model,
            client_message_id=client_message_id,
            owner_instance_id=owner_instance_id,
            expected_status=RUN_STATUS_PENDING,
        )
    except Exception:
        await session.rollback()
        logger.exception(
            "Detached agent turn failed",
            extra={"run_id": str(run_id), "owner_instance_id": owner_instance_id},
        )
    finally:
        heartbeat_stop.set()
        if heartbeat_task is not None:
            heartbeat_task.cancel()
            with suppress(asyncio.CancelledError):
                await heartbeat_task
        await session.close()
        await sink.close()


async def run_resume_worker(
    *,
    run_id: UUID,
    conversation_id: UUID,
    message_history: Sequence[ModelMessage],
    deferred_tool_results: DeferredToolResults,
    sink: EventSink,
    model: Model | None = None,
) -> None:
    """Resume a suspended approval run with an independent DB session."""
    owner_instance_id = _owner_instance_id()
    heartbeat_stop = asyncio.Event()
    heartbeat_task: asyncio.Task[None] | None = None
    session_factory = get_async_db_session_factory()
    session = session_factory()

    try:
        heartbeat_task = asyncio.create_task(
            heartbeat_agent_run_lease(
                run_id=run_id,
                owner_instance_id=owner_instance_id,
                stop=heartbeat_stop,
            ),
            name=f"agent-run-resume-heartbeat:{run_id}",
        )

        await configure_async_db_session(session)
        await execute_run(
            session,
            conversation_id=conversation_id,
            run_id=run_id,
            user_prompt=None,
            sink=sink,
            model=model,
            owner_instance_id=owner_instance_id,
            expected_status=RUN_STATUS_AWAITING_APPROVAL,
            message_history=message_history,
            deferred_tool_results=deferred_tool_results,
        )
    except Exception:
        await session.rollback()
        logger.exception(
            "Detached agent resume failed",
            extra={"run_id": str(run_id), "owner_instance_id": owner_instance_id},
        )
    finally:
        heartbeat_stop.set()
        if heartbeat_task is not None:
            heartbeat_task.cancel()
            with suppress(asyncio.CancelledError):
                await heartbeat_task
        await session.close()
        await sink.close()


def _owner_instance_id() -> str:
    return f"{os.uname().nodename}:{os.getpid()}"
