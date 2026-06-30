# apps/api/services/conversations/delete_conversation.py

"""Soft-delete a conversation."""

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from core.exceptions.general import ConflictError
from models.user import User
from models.workspace import Workspace
from services.agent_runs import reap_abandoned_runs
from services.conversations.utils import get_active_run_for_conversation, get_conversation_for_actor


async def delete_conversation(
    db: AsyncSession,
    *,
    actor: User,
    workspace: Workspace,
    conversation_id: UUID,
) -> None:
    conversation = await get_conversation_for_actor(
        db,
        actor=actor,
        workspace=workspace,
        conversation_id=conversation_id,
    )
    await reap_abandoned_runs(db, conversation_id=conversation.id)
    active_run = await get_active_run_for_conversation(db, conversation_id=conversation.id)
    if active_run is not None:
        raise ConflictError(
            "Conversation has an active agent run",
            conflicting_resource="agent_run",
            details={
                "active_run_id": str(active_run.id),
                "active_run_status": active_run.status,
            },
        )

    conversation.soft_delete(deleted_by=actor.id, cascade=False)
    await db.flush()
