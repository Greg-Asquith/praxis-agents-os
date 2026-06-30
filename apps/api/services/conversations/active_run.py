# apps/api/services/conversations/active_run.py

"""Read the active run for a conversation."""

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from models.user import User
from models.workspace import Workspace
from services.agent_runs import reap_abandoned_runs
from services.conversations.schemas import AgentRunRead, ConversationActiveRunResponse
from services.conversations.utils import get_active_run_for_conversation, get_conversation_for_actor


async def get_conversation_active_run(
    db: AsyncSession,
    *,
    actor: User,
    workspace: Workspace,
    conversation_id: UUID,
) -> ConversationActiveRunResponse:
    """Return the non-terminal run after lazily reaping stale pending/running rows."""
    conversation = await get_conversation_for_actor(
        db,
        actor=actor,
        workspace=workspace,
        conversation_id=conversation_id,
    )
    await reap_abandoned_runs(db, conversation_id=conversation.id)
    active_run = await get_active_run_for_conversation(db, conversation_id=conversation.id)
    return ConversationActiveRunResponse(
        active_run=AgentRunRead.from_run(active_run) if active_run is not None else None
    )
