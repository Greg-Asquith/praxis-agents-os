# apps/api/services/agents/runtime/delegation/delegate_to_agent.py

"""Run a delegated child agent call."""

import asyncio
import logging
from contextlib import suppress
from typing import Annotated
from uuid import UUID

from pydantic import Field
from pydantic_ai import ApprovalRequired, DeferredToolRequests, RunContext

from core.database import configure_async_db_session, get_async_db_session_factory
from models.conversation import CONVERSATION_SOURCE_DELEGATED, Conversation
from services.agent_runs.domain import RUN_TRIGGER_DELEGATED
from services.agents.runtime.context import RuntimeDeps
from services.agents.runtime.delegation.approvals import (
    raise_delegate_approval_required,
)
from services.agents.runtime.delegation.constants import (
    DELEGATE_TASK_MAX_LENGTH,
    DELEGATE_TASK_PREVIEW_MAX_LENGTH,
)
from services.agents.runtime.delegation.get_visible_delegate_agent import (
    get_visible_delegate_agent,
)
from services.agents.runtime.delegation.results import completed_or_failed_result
from services.agents.runtime.delegation.resume_approved_delegate_run import (
    resume_approved_delegate_run,
)
from services.agents.runtime.delegation.schemas import DelegateRunResult
from services.agents.runtime.delegation.utils import (
    heartbeat,
    owner_instance_id,
    safe_error,
    truncate,
)
from services.agents.runtime.sinks import NullSink

logger = logging.getLogger(__name__)


async def delegate_to_agent(
    ctx: RunContext[RuntimeDeps],
    agent_id: UUID,
    task: Annotated[str, Field(min_length=1, max_length=DELEGATE_TASK_MAX_LENGTH)],
) -> DelegateRunResult:
    """Run a delegated child agent call and return a bounded structured result."""
    normalized_task = task.strip()
    if not normalized_task:
        return DelegateRunResult(
            status="failed",
            agent_id=agent_id,
            agent_name="Unknown agent",
            error="Delegate task must not be blank.",
        )

    if ctx.deps.envelope.max_delegation_depth <= ctx.deps.delegation_depth:
        return DelegateRunResult(
            status="failed",
            agent_id=agent_id,
            agent_name="Unknown agent",
            error="Delegation depth limit reached.",
        )

    if ctx.tool_call_approved:
        resumed_result = await resume_approved_delegate_run(
            ctx,
            agent_id=agent_id,
        )
        if resumed_result is not None:
            return resumed_result

    session_factory = get_async_db_session_factory()
    session = session_factory()
    child_run_id: UUID | None = None
    child_conversation_id: UUID | None = None
    target_name = "Unknown agent"
    owner_id = owner_instance_id()
    heartbeat_stop = asyncio.Event()
    heartbeat_task: asyncio.Task[None] | None = None

    try:
        await configure_async_db_session(session)
        target = await get_visible_delegate_agent(
            session,
            caller=ctx.deps.agent,
            workspace=ctx.deps.workspace,
            target_agent_id=agent_id,
        )
        target_name = target.name
        child_conversation = Conversation(
            user_id=ctx.deps.user.id,
            workspace_id=ctx.deps.workspace.id,
            created_by=ctx.deps.user.id,
            title=f"Delegated to {target.name}",
            source=CONVERSATION_SOURCE_DELEGATED,
            active_agent_id=target.id,
            agent_slug=target.slug,
            metadata_json={
                "parent_conversation_id": str(ctx.deps.conversation.id),
                "parent_run_id": str(ctx.deps.run.id),
                "caller_agent_id": str(ctx.deps.agent.id),
                "target_agent_id": str(target.id),
                "task_preview": truncate(
                    normalized_task,
                    DELEGATE_TASK_PREVIEW_MAX_LENGTH,
                )[0],
            },
        )
        session.add(child_conversation)
        await session.flush()

        from services.agent_runs.create import create_agent_run

        child_run = await create_agent_run(
            session,
            conversation_id=child_conversation.id,
            agent_id=target.id,
            workspace_id=ctx.deps.workspace.id,
            user_id=ctx.deps.user.id,
            trigger=RUN_TRIGGER_DELEGATED,
            parent_run_id=ctx.deps.run.id,
            delegation_depth=ctx.deps.delegation_depth + 1,
            metadata={
                "parent_conversation_id": str(ctx.deps.conversation.id),
                "parent_run_id": str(ctx.deps.run.id),
                "caller_agent_id": str(ctx.deps.agent.id),
                "target_agent_id": str(target.id),
                "audit_context": (ctx.deps.run.metadata_json or {}).get(
                    "audit_context"
                ),
            },
        )
        await session.commit()
        child_run_id = child_run.id
        child_conversation_id = child_conversation.id

        heartbeat_task = asyncio.create_task(
            heartbeat(child_run.id, owner_id, heartbeat_stop),
            name=f"delegated-agent-run-heartbeat:{child_run.id}",
        )

        from services.agents.runtime.execute_run import execute_run

        child_result = await execute_run(
            session,
            conversation_id=child_conversation.id,
            run_id=child_run.id,
            user_prompt=normalized_task,
            sink=NullSink(run_id=child_run.id, conversation_id=child_conversation.id),
            owner_instance_id=owner_id,
            usage=ctx.usage,
        )

        if isinstance(child_result.output, DeferredToolRequests):
            raise_delegate_approval_required(
                agent=target,
                run_id=child_result.run.id,
                conversation_id=child_conversation.id,
                deferred_tool_requests=child_result.output,
            )
        return completed_or_failed_result(
            agent=target,
            run=child_result.run,
            conversation_id=child_conversation.id,
            output=child_result.output,
        )
    except ApprovalRequired:
        raise
    except Exception as exc:
        await session.rollback()
        logger.warning(
            "Delegated agent run failed",
            exc_info=True,
            extra={
                "agent_id": str(agent_id),
                "child_run_id": str(child_run_id) if child_run_id else None,
                "parent_run_id": str(ctx.deps.run.id),
            },
        )
        return DelegateRunResult(
            status="failed",
            agent_id=agent_id,
            agent_name=target_name,
            run_id=child_run_id,
            conversation_id=child_conversation_id,
            error=safe_error(exc),
        )
    finally:
        heartbeat_stop.set()
        if heartbeat_task is not None:
            heartbeat_task.cancel()
            with suppress(asyncio.CancelledError):
                await heartbeat_task
        await session.close()
