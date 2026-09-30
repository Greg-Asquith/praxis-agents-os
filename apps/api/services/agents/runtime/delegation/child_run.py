# apps/api/services/agents/runtime/delegation/child_run.py

"""Start and run one delegated child run for a delegate agent or a sub-agent."""

import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

from pydantic_ai import ApprovalRequired, DeferredToolRequests, RunContext
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import (
    configure_async_db_session,
    get_async_db_session_factory,
    set_session_tenant_context,
)
from models.conversation import CONVERSATION_SOURCE_DELEGATED, Conversation
from services.agent_runs.domain import RUN_STATUS_AWAITING_APPROVAL, RUN_TRIGGER_DELEGATED
from services.agents.runtime.context import RuntimeDeps
from services.agents.runtime.delegation.approvals import raise_delegate_approval_required
from services.agents.runtime.delegation.constants import DELEGATE_TASK_PREVIEW_MAX_LENGTH
from services.agents.runtime.delegation.results import completed_or_failed_result
from services.agents.runtime.delegation.schemas import DelegateRunResult
from services.agents.runtime.delegation.utils import safe_error, truncate
from services.agents.runtime.heartbeat import agent_run_owner_instance_id
from services.agents.runtime.sinks import NullSink
from services.agents.runtime.usage_limits import BudgetLimitExceeded, EffectiveUsageLimits

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ChildRunTarget:
    """Who the child run executes as and what its rows record."""

    agent_id: UUID
    agent_name: str
    agent_slug: str
    conversation_title: str
    conversation_metadata: dict[str, Any] = field(default_factory=dict)
    run_metadata: dict[str, Any] = field(default_factory=dict)


async def run_child_agent(
    ctx: RunContext[RuntimeDeps],
    *,
    task: str,
    fallback_agent_id: UUID,
    fallback_agent_name: str,
    resolve_target: Callable[[AsyncSession], Awaitable[ChildRunTarget]],
) -> DelegateRunResult:
    """Create a hidden child conversation and run, execute it, and return a bounded result.

    Approval requests inside the child bubble up to the parent as one delegated approval.
    """
    session_factory = get_async_db_session_factory()
    session = session_factory()
    child_run_id: UUID | None = None
    child_conversation_id: UUID | None = None
    target_name = fallback_agent_name
    owner_id = agent_run_owner_instance_id()
    lineage = {
        "parent_conversation_id": str(ctx.deps.conversation.id),
        "parent_run_id": str(ctx.deps.run.id),
        "caller_agent_id": str(ctx.deps.agent.id),
    }

    try:
        await configure_async_db_session(session)
        await set_session_tenant_context(
            session,
            workspace_id=ctx.deps.workspace.id,
            user_id=ctx.deps.user.id,
        )
        target = await resolve_target(session)
        target_name = target.agent_name
        child_conversation = Conversation(
            user_id=ctx.deps.user.id,
            workspace_id=ctx.deps.workspace.id,
            created_by=ctx.deps.user.id,
            title=target.conversation_title,
            source=CONVERSATION_SOURCE_DELEGATED,
            active_agent_id=target.agent_id,
            agent_slug=target.agent_slug,
            metadata_json={
                **lineage,
                **target.conversation_metadata,
                "task_preview": truncate(task, DELEGATE_TASK_PREVIEW_MAX_LENGTH)[0],
            },
        )
        session.add(child_conversation)
        await session.flush()

        from services.agent_runs.create import create_agent_run

        child_run = await create_agent_run(
            session,
            conversation_id=child_conversation.id,
            agent_id=target.agent_id,
            workspace_id=ctx.deps.workspace.id,
            user_id=ctx.deps.user.id,
            trigger=RUN_TRIGGER_DELEGATED,
            parent_run_id=ctx.deps.run.id,
            parent_owner_instance_id=ctx.deps.execution_control.owner_instance_id
            if ctx.deps.execution_control
            else ctx.deps.run.owner_instance_id,
            delegation_depth=ctx.deps.delegation_depth + 1,
            metadata={
                **lineage,
                **target.run_metadata,
                "audit_context": (ctx.deps.run.metadata_json or {}).get("audit_context"),
                "envelope": {
                    "side_effect_policy": ctx.deps.envelope.side_effect_policy,
                },
            },
        )
        await session.commit()
        child_run_id = child_run.id
        child_conversation_id = child_conversation.id

        from services.agents.runtime.execute_run import execute_run

        child_result = await execute_run(
            session,
            conversation_id=child_conversation.id,
            run_id=child_run.id,
            user_prompt=task,
            sink=NullSink(run_id=child_run.id, conversation_id=child_conversation.id),
            owner_instance_id=owner_id,
            usage=ctx.usage,
            inherited_usage_limits=EffectiveUsageLimits.from_sdk(ctx.usage_limits),
            parent_metering=ctx.deps.metering,
            root_execution=ctx.deps.execution_control,
        )

        if child_result.run.status == RUN_STATUS_AWAITING_APPROVAL and isinstance(
            child_result.output, DeferredToolRequests
        ):
            raise_delegate_approval_required(
                agent_id=target.agent_id,
                agent_name=target_name,
                run_id=child_result.run.id,
                conversation_id=child_conversation.id,
                deferred_tool_requests=child_result.output,
            )
        return completed_or_failed_result(
            agent_name=target_name,
            run=child_result.run,
            conversation_id=child_result.run.conversation_id,
            output=child_result.output,
        )
    except (ApprovalRequired, BudgetLimitExceeded):
        raise
    except Exception as exc:
        await session.rollback()
        logger.warning(
            "Delegated agent run failed",
            exc_info=True,
            extra={
                "agent_id": str(fallback_agent_id),
                "child_run_id": str(child_run_id) if child_run_id else None,
                "parent_run_id": str(ctx.deps.run.id),
            },
        )
        return DelegateRunResult(
            status="failed",
            agent_id=fallback_agent_id,
            agent_name=target_name,
            run_id=child_run_id,
            conversation_id=child_conversation_id,
            error=safe_error(exc),
        )
    finally:
        await session.close()
