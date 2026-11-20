# apps/api/services/conversation_review/collect_finished_conversations.py

"""Find the conversations that finished a run inside a review window."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from models.agent_run import AgentRun
from models.conversation import CONVERSATION_SOURCE_DIRECT, Conversation, ConversationMessage
from services.agent_runs.domain import RUN_STATUS_COMPLETED
from services.conversation_review.domain import FinishedConversation


async def collect_finished_conversations(
    db: AsyncSession,
    *,
    workspace_id: UUID,
    window_start: datetime | None,
    window_end: datetime,
    limit: int,
) -> list[FinishedConversation]:
    """Returns direct conversations with a run completed in (start, end], oldest first."""
    first_finished = func.min(AgentRun.completed_at).label("first_finished_at")
    stmt = (
        select(Conversation.id, Conversation.user_id, Conversation.visibility, first_finished)
        .join(AgentRun, AgentRun.conversation_id == Conversation.id)
        .where(
            Conversation.workspace_id == workspace_id,
            Conversation.deleted.is_(False),
            Conversation.source == CONVERSATION_SOURCE_DIRECT,
            AgentRun.workspace_id == workspace_id,
            AgentRun.deleted.is_(False),
            AgentRun.status == RUN_STATUS_COMPLETED,
            AgentRun.completed_at <= window_end,
        )
        .group_by(Conversation.id)
        .order_by(first_finished, Conversation.id)
        .limit(limit)
    )
    if window_start is not None:
        stmt = stmt.where(AgentRun.completed_at > window_start)
    rows = (await db.execute(stmt)).all()
    if not rows:
        return []
    ids = [row.id for row in rows]
    agents = dict(
        (
            await db.execute(
                select(AgentRun.conversation_id, AgentRun.agent_id)
                .where(
                    AgentRun.conversation_id.in_(ids),
                    AgentRun.status == RUN_STATUS_COMPLETED,
                    AgentRun.completed_at <= window_end,
                )
                .distinct(AgentRun.conversation_id)
                .order_by(AgentRun.conversation_id, AgentRun.completed_at.desc())
            )
        )
        .tuples()
        .all()
    )
    ends = dict(
        (
            await db.execute(
                select(ConversationMessage.conversation_id, func.max(ConversationMessage.sequence))
                .where(
                    ConversationMessage.conversation_id.in_(ids),
                    ConversationMessage.deleted.is_(False),
                )
                .group_by(ConversationMessage.conversation_id)
            )
        )
        .tuples()
        .all()
    )
    return [
        FinishedConversation(
            id=row.id,
            user_id=row.user_id,
            agent_id=agents[row.id],
            visibility=row.visibility,
            first_finished_at=row.first_finished_at,
            end_sequence=ends[row.id] + 1,
        )
        for row in rows
        if row.id in ends
    ]
