# apps/api/services/conversations/update_sharing.py

"""Changes the audience of one conversation."""

from datetime import UTC, datetime
from typing import Literal
from uuid import UUID

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

from core.exceptions.general import AppValidationError, NotFoundError
from models.user import User
from models.workspace import Workspace
from services.audit_events import AuditAction, AuditActorType, AuditResourceType
from services.audit_events.operations import record_operation_audit_event
from services.conversation_read_contract import ConversationRead, SharedConversationRead
from services.conversations.get_conversation import get_conversation
from services.conversations.utils import (
    conversation_capabilities,
    get_conversation_for_read,
    shared_conversation_read,
)


async def update_conversation_sharing(
    db: AsyncSession,
    *,
    actor: User,
    workspace: Workspace,
    conversation_id: UUID,
    visibility: Literal["private", "workspace"],
    request: Request | None = None,
) -> ConversationRead | SharedConversationRead:
    """Updates visibility and audit evidence in the caller's transaction."""
    conversation, membership = await get_conversation_for_read(
        db,
        actor=actor,
        workspace=workspace,
        conversation_id=conversation_id,
        lock=True,
    )
    capabilities = conversation_capabilities(
        conversation, actor=actor, workspace=workspace, membership=membership
    )
    if workspace.is_personal or conversation.source == "delegated":
        raise AppValidationError("This chat cannot be shared with a workspace", field="visibility")
    allowed = (
        capabilities.can_manage_sharing
        if visibility == "workspace"
        else (capabilities.can_manage_sharing or capabilities.can_stop_sharing)
    )
    if not allowed:
        raise NotFoundError(
            "Conversation not found", resource_type="conversation", resource_id=str(conversation_id)
        )
    previous = conversation.visibility
    if previous != visibility:
        conversation.visibility = visibility
        conversation.shared_at = datetime.now(UTC) if visibility == "workspace" else None
        conversation.shared_by_user_id = actor.id if visibility == "workspace" else None
        await record_operation_audit_event(
            db,
            workspace_id=workspace.id,
            action=AuditAction.ENABLE if visibility == "workspace" else AuditAction.DISABLE,
            resource_type=AuditResourceType.CONVERSATION_SHARING,
            resource_id=conversation.id,
            actor_type=AuditActorType.USER,
            actor_id=actor.id,
            actor_display=actor.display_name,
            requested_by_user_id=actor.id,
            request=request,
            details={"previous_visibility": previous, "visibility": visibility},
        )
    # A manager's successful revocation removes their read access immediately.
    if conversation.user_id != actor.id:
        await db.refresh(conversation, attribute_names=["updated_at"])
        return shared_conversation_read(
            conversation,
            owner_name=None,
            agent_name=None,
            active_run_status=None,
            capabilities=conversation_capabilities(
                conversation, actor=actor, workspace=workspace, membership=membership
            ),
        )
    return await get_conversation(
        db, actor=actor, workspace=workspace, conversation_id=conversation_id
    )
