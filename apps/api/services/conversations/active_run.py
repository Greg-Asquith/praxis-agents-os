# apps/api/services/conversations/active_run.py

"""Read the active run for a conversation."""

from datetime import timedelta
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from core.settings import settings
from models.user import User
from models.workspace import Workspace
from services.agent_runs import reap_abandoned_runs
from services.agent_runs.domain import RUN_STATUS_AWAITING_APPROVAL
from services.conversations.schemas import AgentRunRead, ConversationActiveRunResponse
from services.conversations.utils import (
    get_active_run_for_conversation,
    get_conversation_for_actor,
    get_latest_run_for_conversation,
)


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
    latest_run = active_run
    if latest_run is None:
        latest_run = await get_latest_run_for_conversation(db, conversation_id=conversation.id)
    approval_expires_at = None
    if (
        active_run is not None
        and active_run.status == RUN_STATUS_AWAITING_APPROVAL
        and settings.AGENT_RUN_APPROVAL_EXPIRY_DAYS > 0
    ):
        approval_expires_at = active_run.updated_at + timedelta(
            days=settings.AGENT_RUN_APPROVAL_EXPIRY_DAYS
        )
    return ConversationActiveRunResponse(
        active_run=AgentRunRead.from_run(active_run) if active_run is not None else None,
        latest_run=AgentRunRead.from_run(latest_run) if latest_run is not None else None,
        approval_expires_at=approval_expires_at,
    )
