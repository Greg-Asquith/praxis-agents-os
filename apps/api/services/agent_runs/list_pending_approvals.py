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
from services.agent_runs.get_approval_state import get_agent_run_approval_state
from services.agent_runs.schemas import (
    PendingApprovalRunRead,
    PendingApprovalsListResponse,
)

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
            projection = await get_agent_run_approval_state(
                db, actor=actor, workspace=workspace, run_id=run.id
            )
            pending_tool_names = [approval.name for approval in projection.approvals]
            delegated_agent_names = [item.child_agent_name for item in projection.delegations]
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
