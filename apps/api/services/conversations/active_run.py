# apps/api/services/conversations/active_run.py

"""Read the active run for a conversation."""

from datetime import timedelta
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.settings import settings
from models.agent_run import AgentRun
from models.conversation import Conversation
from models.user import User
from models.workspace import Workspace
from services.agent_runs import reap_abandoned_runs
from services.agent_runs.domain import RUN_STATUS_AWAITING_APPROVAL
from services.agents.runtime.approval_identity import (
    APPROVAL_REVISION_KEY,
    validate_approval_identity_metadata,
)
from services.agents.runtime.approval_state import load_suspended_run_state
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
    root_run = await _verified_root_run(db, run=latest_run, actor=actor, workspace=workspace)
    return ConversationActiveRunResponse(
        approval_revision=_saved_approval_revision(active_run),
        root_run_id=root_run.id if root_run is not None else None,
        root_conversation_id=root_run.conversation_id if root_run is not None else None,
        active_run=AgentRunRead.from_run(active_run) if active_run is not None else None,
        latest_run=AgentRunRead.from_run(latest_run) if latest_run is not None else None,
        approval_expires_at=approval_expires_at,
    )


def _saved_approval_revision(run: AgentRun | None) -> str | None:
    """Returns a validated stored revision without activating graph projection."""
    if run is None or run.status != RUN_STATUS_AWAITING_APPROVAL:
        return None
    metadata = run.metadata_json
    raw = metadata.get("approval_state") if isinstance(metadata, dict) else None
    if not isinstance(raw, dict):
        return None
    validate_approval_identity_metadata(raw)
    revision = raw.get(APPROVAL_REVISION_KEY)
    if revision is not None:
        load_suspended_run_state(run)
    return revision


async def _verified_root_run(
    db: AsyncSession, *, run: AgentRun | None, actor: User, workspace: Workspace
) -> AgentRun | None:
    """Resolves a child transcript's main conversation through canonical ownership."""
    if (
        run is None
        or run.parent_run_id is None
        or run.delegation_depth != 1
        or run.user_id != actor.id
        or run.workspace_id != workspace.id
    ):
        return None
    return await db.scalar(
        select(AgentRun)
        .join(Conversation, Conversation.id == AgentRun.conversation_id)
        .where(
            AgentRun.id == run.parent_run_id,
            AgentRun.parent_run_id.is_(None),
            AgentRun.delegation_depth == 0,
            AgentRun.user_id == actor.id,
            AgentRun.workspace_id == workspace.id,
            AgentRun.deleted.is_(False),
            Conversation.user_id == actor.id,
            Conversation.workspace_id == workspace.id,
            Conversation.deleted.is_(False),
        )
    )
