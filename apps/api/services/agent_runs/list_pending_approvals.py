# apps/api/services/agent_runs/list_pending_approvals.py

"""List suspended top-level runs that need the current actor's approval."""

import logging

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from core.exceptions.general import ConflictError
from models.agent import Agent
from models.agent_run import AgentRun
from models.conversation import Conversation
from models.user import User
from models.workspace import Workspace
from services.agent_runs.domain import RUN_STATUS_AWAITING_APPROVAL
from services.agent_runs.schemas import (
    PendingApprovalRunRead,
    PendingApprovalsListResponse,
)
from services.agent_runs.utils import load_delegated_child_run_for_approval
from services.agents.delegation_approval import (
    DELEGATED_APPROVAL_CHILD_AGENT_NAME_KEY,
)
from services.agents.runtime.approval_state import load_suspended_run_state
from utils.metadata import metadata_str

logger = logging.getLogger(__name__)


async def list_pending_agent_run_approvals(
    db: AsyncSession,
    *,
    actor: User,
    workspace: Workspace,
    limit: int = 20,
) -> PendingApprovalsListResponse:
    """Return the oldest top-level approval waits visible to the actor."""
    filters = (
        AgentRun.status == RUN_STATUS_AWAITING_APPROVAL,
        AgentRun.workspace_id == workspace.id,
        AgentRun.user_id == actor.id,
        AgentRun.deleted == False,  # noqa: E712
        AgentRun.parent_run_id.is_(None),
    )
    total = await db.scalar(select(func.count()).select_from(AgentRun).where(*filters))
    rows = (
        await db.execute(
            select(AgentRun, Conversation.title, Agent.name)
            .join(Conversation, Conversation.id == AgentRun.conversation_id)
            .outerjoin(Agent, Agent.id == AgentRun.agent_id)
            .where(*filters)
            .order_by(AgentRun.updated_at.asc(), AgentRun.id.asc())
            .limit(limit)
        )
    ).all()

    items: list[PendingApprovalRunRead] = []
    for run, conversation_title, agent_name in rows:
        try:
            pending_tool_names, delegated_agent_names = await _pending_names(db, run)
        except ConflictError:
            logger.warning(
                "Skipping pending approval run with invalid suspended state",
                extra={"run_id": str(run.id)},
                exc_info=True,
            )
            continue

        items.append(
            PendingApprovalRunRead(
                run_id=run.id,
                conversation_id=run.conversation_id,
                conversation_title=conversation_title,
                agent_id=run.agent_id,
                agent_name=agent_name,
                awaiting_since=run.updated_at,
                pending_tool_names=pending_tool_names,
                delegated_agent_names=delegated_agent_names,
            )
        )

    return PendingApprovalsListResponse(items=items, total=total or 0)


async def _pending_names(
    db: AsyncSession,
    run: AgentRun,
) -> tuple[list[str], list[str]]:
    suspended_state = load_suspended_run_state(run)
    pending_tool_names: list[str] = []
    delegated_agent_names: list[str] = []

    for approval in suspended_state.deferred_tool_requests.approvals:
        metadata = suspended_state.deferred_tool_requests.metadata.get(approval.tool_call_id)
        child_run = await load_delegated_child_run_for_approval(
            db,
            parent_run=run,
            metadata=metadata,
        )
        if child_run is None:
            pending_tool_names.append(approval.tool_name)
            continue

        load_suspended_run_state(child_run)
        delegated_agent_names.append(
            metadata_str(metadata.get(DELEGATED_APPROVAL_CHILD_AGENT_NAME_KEY)) or "Delegate agent"
        )

    return pending_tool_names, delegated_agent_names
