# apps/api/services/agents/runtime/delegation/resume_approved_delegate_run.py

"""Resume a delegated child run after approval."""

import logging
from uuid import UUID

from pydantic import TypeAdapter
from pydantic_ai import ApprovalRequired, DeferredToolRequests, DeferredToolResults, RunContext
from sqlalchemy import select

from core.database import (
    configure_async_db_session,
    get_async_db_session_factory,
    set_session_tenant_context,
)
from core.exceptions.general import ConflictError, NotFoundError
from models.agent_run import AgentRun
from models.conversation import Conversation
from services.agent_runs.continuation_state import AgentRunResumeRequiresRecoveryError
from services.agent_runs.domain import RUN_STATUS_AWAITING_APPROVAL, RUN_STATUS_RUNNING
from services.agent_runs.execution_state import require_execution_owner
from services.agent_runs.settle_run_family import lock_run_family
from services.agents.delegation_approval import (
    DELEGATED_APPROVAL_CHILD_AGENT_NAME_KEY,
    DELEGATED_APPROVAL_CHILD_DEFERRED_TOOL_RESULTS_KEY,
    DELEGATED_APPROVAL_CHILD_RUN_ID_KEY,
    DELEGATED_APPROVAL_KIND,
    DELEGATED_APPROVAL_KIND_KEY,
)
from services.agents.runtime.approval_state import load_suspended_run_state
from services.agents.runtime.context import RuntimeDeps
from services.agents.runtime.delegation.approvals import (
    raise_delegate_approval_required,
)
from services.agents.runtime.delegation.get_visible_delegate_agent import (
    get_visible_delegate_agent,
)
from services.agents.runtime.delegation.results import (
    completed_or_failed_result,
    fail_child_run_delegate_not_allowed,
)
from services.agents.runtime.delegation.schemas import DelegateRunResult
from services.agents.runtime.heartbeat import agent_run_owner_instance_id
from services.agents.runtime.sinks import NullSink
from services.agents.runtime.usage_limits import BudgetLimitExceeded, EffectiveUsageLimits
from utils.metadata import metadata_str, metadata_uuid

logger = logging.getLogger(__name__)

_DEFERRED_TOOL_RESULTS_ADAPTER = TypeAdapter(DeferredToolResults)


async def resume_approved_delegate_run(
    ctx: RunContext[RuntimeDeps],
    *,
    agent_id: UUID,
) -> DelegateRunResult:
    from services.agent_runs.claim_child_approval import claim_child_approval

    metadata = ctx.tool_call_metadata
    if not isinstance(metadata, dict):
        raise AgentRunResumeRequiresRecoveryError()
    if metadata.get(DELEGATED_APPROVAL_KIND_KEY) != DELEGATED_APPROVAL_KIND:
        raise AgentRunResumeRequiresRecoveryError()

    child_run_id = metadata_uuid(metadata.get(DELEGATED_APPROVAL_CHILD_RUN_ID_KEY))
    child_deferred_results_raw = metadata.get(DELEGATED_APPROVAL_CHILD_DEFERRED_TOOL_RESULTS_KEY)
    if child_run_id is None or child_deferred_results_raw is None:
        raise AgentRunResumeRequiresRecoveryError()
    try:
        child_deferred_results = _DEFERRED_TOOL_RESULTS_ADAPTER.validate_python(
            child_deferred_results_raw
        )
    except Exception as exc:
        raise AgentRunResumeRequiresRecoveryError() from exc

    session_factory = get_async_db_session_factory()
    session = session_factory()
    owner_id = agent_run_owner_instance_id()

    try:
        await configure_async_db_session(session)
        await set_session_tenant_context(
            session,
            workspace_id=ctx.deps.workspace.id,
            user_id=ctx.deps.user.id,
        )
        family = await lock_run_family(session, run_id=ctx.deps.run.id)
        if not family or family[0].status != RUN_STATUS_RUNNING:
            raise ConflictError(
                "Parent run is no longer executable", conflicting_resource="agent_run"
            )
        if ctx.deps.execution_control is not None:
            require_execution_owner(family[0], ctx.deps.execution_control.owner_instance_id)
        child_run = await session.scalar(
            select(AgentRun).where(
                AgentRun.id == child_run_id,
                AgentRun.parent_run_id == ctx.deps.run.id,
                AgentRun.workspace_id == ctx.deps.workspace.id,
                AgentRun.user_id == ctx.deps.user.id,
                AgentRun.deleted == False,  # noqa: E712
            )
        )
        if child_run is None:
            raise NotFoundError(
                "Delegated child run not found",
                resource_type="agent_run",
                resource_id=str(child_run_id),
            )

        child_conversation = await session.get(Conversation, child_run.conversation_id)
        if child_conversation is None:
            raise NotFoundError(
                "Delegated child conversation not found",
                resource_type="conversation",
                resource_id=str(child_run.conversation_id),
            )

        try:
            target = await get_visible_delegate_agent(
                session,
                caller=ctx.deps.agent,
                workspace=ctx.deps.workspace,
                target_agent_id=child_run.agent_id,
            )
        except NotFoundError:
            await fail_child_run_delegate_not_allowed(
                session,
                child_run=child_run,
                conversation_id=child_conversation.id,
                agent_name=metadata_str(metadata.get(DELEGATED_APPROVAL_CHILD_AGENT_NAME_KEY))
                or "Unknown agent",
            )

            raise AgentRunResumeRequiresRecoveryError() from None

        target_name = target.name
        suspended_state = load_suspended_run_state(child_run)
        await claim_child_approval(
            session,
            root=family[0],
            child=child_run,
            parent_tool_call_id=ctx.tool_call_id,
            root_owner=ctx.deps.execution_control.owner_instance_id
            if ctx.deps.execution_control
            else ctx.deps.run.owner_instance_id,
            child_owner=owner_id,
            results=child_deferred_results,
        )
        from services.agents.runtime.execute_run import execute_run

        child_result = await execute_run(
            session,
            conversation_id=child_conversation.id,
            run_id=child_run.id,
            user_prompt=None,
            sink=NullSink(run_id=child_run.id, conversation_id=child_conversation.id),
            owner_instance_id=owner_id,
            expected_status=RUN_STATUS_RUNNING,
            message_history=suspended_state.message_history,
            deferred_tool_results=child_deferred_results,
            usage=ctx.usage,
            inherited_usage_limits=EffectiveUsageLimits.from_sdk(ctx.usage_limits),
            parent_metering=ctx.deps.metering,
            root_execution=ctx.deps.execution_control,
        )

        if child_result.run.status == RUN_STATUS_AWAITING_APPROVAL and isinstance(
            child_result.output, DeferredToolRequests
        ):
            raise_delegate_approval_required(
                agent=target,
                run_id=child_result.run.id,
                conversation_id=child_conversation.id,
                deferred_tool_requests=child_result.output,
            )
        if (
            child_result.run.status != "completed"
            and child_result.run.outcome != "budget_exhausted"
        ):
            raise AgentRunResumeRequiresRecoveryError()
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
            "Delegated agent resume failed",
            exc_info=True,
            extra={
                "agent_id": str(agent_id),
                "child_run_id": str(child_run_id),
                "parent_run_id": str(ctx.deps.run.id),
            },
        )
        raise AgentRunResumeRequiresRecoveryError() from exc
    finally:
        await session.close()
