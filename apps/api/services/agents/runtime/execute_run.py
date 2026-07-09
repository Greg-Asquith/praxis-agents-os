# apps/api/services/agents/runtime/execute_run.py

"""Compatibility module for the agent run execution entry point."""

from collections.abc import Sequence
from uuid import UUID

from pydantic_ai import DeferredToolResults
from pydantic_ai.messages import ModelMessage, UserContent
from pydantic_ai.models import Model
from pydantic_ai.usage import RunUsage
from sqlalchemy.ext.asyncio import AsyncSession

from services.agent_runs.domain import RUN_STATUS_PENDING
from services.agents.runtime.envelope import build_run_envelope
from services.agents.runtime.execute.execute_run import execute_run_with_builders
from services.agents.runtime.execute.types import ExecuteRunResult
from services.agents.runtime.loop import build_runtime_agent
from services.agents.runtime.sinks import EventSink


async def execute_run(
    db: AsyncSession,
    *,
    conversation_id: UUID,
    run_id: UUID,
    user_prompt: str | Sequence[UserContent] | None,
    attachment_file_ids: Sequence[UUID] = (),
    sink: EventSink | None = None,
    model: Model | None = None,
    client_message_id: str | None = None,
    owner_instance_id: str | None = None,
    expected_status: str | None = RUN_STATUS_PENDING,
    message_history: Sequence[ModelMessage] | None = None,
    deferred_tool_results: DeferredToolResults | None = None,
    usage: RunUsage | None = None,
) -> ExecuteRunResult:
    """Drive one agent turn to completion or approval suspension.

    New turn prompts are persisted before provider streaming so cancellation does
    not lose the user message. Resume callers pass rehydrated
    ``message_history`` and ``deferred_tool_results`` instead of a new prompt.
    This function owns the run lifecycle transaction boundaries: it commits the
    running+lease state before provider streaming, commits final
    messages/usage/status after the stream, and commits failures before
    re-raising so rollback-based dependencies do not erase diagnostic state.
    """
    return await execute_run_with_builders(
        db,
        conversation_id=conversation_id,
        run_id=run_id,
        user_prompt=user_prompt,
        attachment_file_ids=attachment_file_ids,
        sink=sink,
        model=model,
        client_message_id=client_message_id,
        owner_instance_id=owner_instance_id,
        expected_status=expected_status,
        message_history=message_history,
        deferred_tool_results=deferred_tool_results,
        usage=usage,
        runtime_agent_builder=build_runtime_agent,
        run_envelope_builder=build_run_envelope,
    )


__all__ = [
    "ExecuteRunResult",
    "build_run_envelope",
    "build_runtime_agent",
    "execute_run",
]
