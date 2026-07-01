# apps/api/services/conversations/list_conversations.py

"""List conversations visible to the authenticated user in a workspace."""

from sqlalchemy import and_, desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from models.agent import Agent
from models.agent_run import AgentRun
from models.conversation import Conversation
from models.user import User
from models.workspace import Workspace
from services.agent_runs.domain import (
    RUN_STATUS_AWAITING_APPROVAL,
    RUN_STATUS_PENDING,
    RUN_STATUS_RUNNING,
)
from services.conversations.schemas import ConversationRead, ConversationsListResponse

ACTIVE_RUN_STATUSES = frozenset(
    {RUN_STATUS_PENDING, RUN_STATUS_RUNNING, RUN_STATUS_AWAITING_APPROVAL}
)


async def list_conversations(
    db: AsyncSession,
    *,
    actor: User,
    workspace: Workspace,
    limit: int,
    offset: int,
) -> ConversationsListResponse:
    filters = (
        Conversation.workspace_id == workspace.id,
        Conversation.user_id == actor.id,
        Conversation.deleted == False,  # noqa: E712
    )
    total = await db.scalar(select(func.count()).select_from(Conversation).where(*filters))
    active_runs = (
        select(
            AgentRun.id.label("active_run_id"),
            AgentRun.conversation_id.label("conversation_id"),
            AgentRun.status.label("active_run_status"),
            # More than one active run is a lifecycle anomaly; project the newest
            # one so the list remains stable without repairing data in a read path.
            func.row_number()
            .over(
                partition_by=AgentRun.conversation_id,
                order_by=(AgentRun.created_at.desc(), AgentRun.id.desc()),
            )
            .label("active_run_rank"),
        )
        .where(
            AgentRun.deleted == False,  # noqa: E712
            AgentRun.status.in_(ACTIVE_RUN_STATUSES),
        )
        .subquery()
    )
    stmt = (
        select(
            Conversation,
            Agent.name.label("agent_name"),
            active_runs.c.active_run_id,
            active_runs.c.active_run_status,
        )
        .outerjoin(
            Agent,
            and_(
                Conversation.active_agent_id == Agent.id,
                Agent.workspace_id == workspace.id,
            ),
        )
        .outerjoin(
            active_runs,
            and_(
                active_runs.c.conversation_id == Conversation.id,
                active_runs.c.active_run_rank == 1,
            ),
        )
        .where(*filters)
    )
    rows = (
        await db.execute(
            stmt.order_by(
                desc(func.coalesce(Conversation.last_message_at, Conversation.created_at)),
                Conversation.created_at.desc(),
            )
            .limit(limit)
            .offset(offset)
        )
    ).all()
    return ConversationsListResponse(
        conversations=[
            ConversationRead.from_projection(
                conversation,
                agent_name=agent_name,
                active_run_id=active_run_id,
                active_run_status=active_run_status,
            )
            for conversation, agent_name, active_run_id, active_run_status in rows
        ],
        total=total or 0,
        limit=limit,
        offset=offset,
    )
