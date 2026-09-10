# apps/api/services/conversations/utils.py

"""Helpers specific to the conversations service."""

from collections.abc import Sequence
from hashlib import sha256
from typing import Any
from uuid import UUID

from fastapi import Request
from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from core.exceptions.general import ConflictError, NotFoundError
from models.agent import Agent
from models.agent_run import AgentRun
from models.conversation import CONVERSATION_SOURCE_DELEGATED, Conversation, ConversationMessage
from models.user import User
from models.workspace import Workspace, WorkspaceMembership
from services.agent_runs.domain import TERMINAL_RUN_STATUSES
from services.audit_events.utils import request_audit_context
from services.conversation_read_contract import (
    ConversationCapabilities,
    SharedConversationRead,
)
from services.workspaces.utils import (
    MANAGER_ROLES,
    READ_ROLES,
    require_workspace_role,
)


def build_interactive_run_metadata(
    *,
    client_message_id: str | None,
    request: Request | None,
    attachment_file_ids: Sequence[UUID] = (),
) -> dict[str, Any] | None:
    """Build metadata persisted with an interactive agent run."""
    metadata: dict[str, Any] = {}
    if client_message_id:
        metadata["client_message_id"] = client_message_id
    if attachment_file_ids:
        metadata["attachment_file_ids"] = [str(file_id) for file_id in attachment_file_ids]
    if request is not None:
        metadata["audit_context"] = request_audit_context(request)
    return metadata or None


async def lock_conversation_turn(
    db: AsyncSession,
    *,
    conversation_id: UUID,
) -> None:
    """Serialize active-run checks and inserts for one conversation."""
    lock_material = f"conversation-turn:{conversation_id}".encode()
    lock_key = int.from_bytes(sha256(lock_material).digest()[:8], "big", signed=True)
    await db.execute(select(func.pg_advisory_xact_lock(lock_key)))


async def get_conversation_for_actor(
    db: AsyncSession,
    *,
    actor: User,
    workspace: Workspace,
    conversation_id: UUID,
    lock: bool = False,
) -> Conversation:
    """Loads a conversation owned by the current actor."""
    statement = select(Conversation).where(
        Conversation.id == conversation_id,
        Conversation.workspace_id == workspace.id,
        Conversation.user_id == actor.id,
        Conversation.deleted.is_(False),
    )
    if lock:
        statement = statement.with_for_update().execution_options(populate_existing=True)
    conversation = await db.scalar(statement)
    if conversation is None:
        raise NotFoundError(
            "Conversation not found",
            resource_type="conversation",
            resource_id=str(conversation_id),
        )
    return conversation


async def get_assignable_agent_for_workspace(
    db: AsyncSession,
    *,
    workspace: Workspace,
    agent_id: UUID,
) -> Agent:
    """Load an active agent that can be assigned to a new conversation."""
    agent = await db.scalar(
        select(Agent).where(
            Agent.id == agent_id,
            Agent.workspace_id == workspace.id,
            Agent.deleted == False,  # noqa: E712
        )
    )
    if agent is None:
        raise NotFoundError(
            "Agent not found",
            resource_type="agent",
            resource_id=str(agent_id),
        )
    if not agent.is_active:
        raise ConflictError(
            "Agent is not active",
            conflicting_resource="agent",
            details={"agent_id": str(agent.id)},
        )
    return agent


async def get_active_run_for_conversation(
    db: AsyncSession,
    *,
    conversation_id: UUID,
) -> AgentRun | None:
    """Return the newest non-terminal run for a conversation, if any."""
    return await db.scalar(
        select(AgentRun)
        .where(
            AgentRun.conversation_id == conversation_id,
            AgentRun.deleted == False,  # noqa: E712
            AgentRun.status.not_in(TERMINAL_RUN_STATUSES),
        )
        .order_by(AgentRun.created_at.desc())
        .limit(1)
    )


async def get_latest_run_for_conversation(
    db: AsyncSession,
    *,
    conversation_id: UUID,
) -> AgentRun | None:
    """Return the newest run for a conversation, including terminal outcomes."""
    return await db.scalar(
        select(AgentRun)
        .where(
            AgentRun.conversation_id == conversation_id,
            AgentRun.deleted == False,  # noqa: E712
        )
        .order_by(AgentRun.created_at.desc(), AgentRun.id.desc())
        .limit(1)
    )


async def get_conversation_agent_name(
    db: AsyncSession,
    *,
    conversation: Conversation,
) -> str | None:
    """Return the active agent display name for a conversation, if one is assigned."""
    if conversation.active_agent_id is None:
        return None
    return await db.scalar(
        select(Agent.name).where(
            Agent.id == conversation.active_agent_id,
            Agent.workspace_id == conversation.workspace_id,
        )
    )


async def get_message_by_client_message_id(
    db: AsyncSession,
    *,
    conversation_id: UUID,
    client_message_id: str,
) -> ConversationMessage | None:
    """Return an existing conversation message for a caller-supplied idempotency key."""
    return await db.scalar(
        select(ConversationMessage).where(
            ConversationMessage.conversation_id == conversation_id,
            ConversationMessage.client_message_id == client_message_id,
            ConversationMessage.deleted == False,  # noqa: E712
        )
    )


def shared_conversation_predicate(workspace: Workspace) -> ColumnElement[bool]:
    """Selects live shared root chats in a team workspace."""
    return and_(
        Conversation.workspace_id == workspace.id,
        Conversation.deleted.is_(False),
        Conversation.visibility == "workspace",
        Conversation.source != CONVERSATION_SOURCE_DELEGATED,
        not workspace.is_personal,
        workspace.status == "active",
    )


async def get_conversation_for_read(
    db: AsyncSession,
    *,
    actor: User,
    workspace: Workspace,
    conversation_id: UUID,
    lock: bool = False,
) -> tuple[Conversation, WorkspaceMembership]:
    """Authorises transcript reads without granting execution ownership."""
    _, membership = await require_workspace_role(
        db, actor=actor, workspace_id=workspace.id, allowed_roles=READ_ROLES
    )
    statement = select(Conversation).where(
        Conversation.id == conversation_id,
        Conversation.workspace_id == workspace.id,
        Conversation.deleted.is_(False),
        or_(Conversation.user_id == actor.id, shared_conversation_predicate(workspace)),
    )
    if lock:
        statement = statement.with_for_update().execution_options(populate_existing=True)
    conversation = await db.scalar(statement)
    if conversation is None or workspace.status != "active":
        raise NotFoundError(
            "Conversation not found", resource_type="conversation", resource_id=str(conversation_id)
        )
    return conversation, membership


def conversation_capabilities(
    conversation: Conversation,
    *,
    actor: User,
    workspace: Workspace,
    membership: WorkspaceMembership,
) -> ConversationCapabilities:
    """Derives sharing and reply controls from current ownership and membership."""
    owner = conversation.user_id == actor.id
    eligible = not workspace.is_personal and conversation.source != CONVERSATION_SOURCE_DELEGATED
    return ConversationCapabilities(
        can_reply=owner and conversation.source != CONVERSATION_SOURCE_DELEGATED,
        can_manage_sharing=owner and eligible,
        can_stop_sharing=eligible
        and conversation.visibility == "workspace"
        and (owner or membership.role in MANAGER_ROLES),
    )


def shared_conversation_read(
    conversation: Conversation,
    *,
    owner_name: str | None,
    agent_name: str | None,
    active_run_status: str | None,
    capabilities: ConversationCapabilities,
) -> SharedConversationRead:
    """Projects saved conversation labels without owner execution state."""
    return SharedConversationRead(
        id=conversation.id,
        workspace_id=conversation.workspace_id,
        title=conversation.title,
        source=conversation.source,
        visibility=conversation.visibility,
        owner_name=owner_name,
        agent_name=agent_name,
        last_message_at=conversation.last_message_at,
        active_run_status=active_run_status,
        created_at=conversation.created_at,
        updated_at=conversation.updated_at,
        capabilities=capabilities,
    )
