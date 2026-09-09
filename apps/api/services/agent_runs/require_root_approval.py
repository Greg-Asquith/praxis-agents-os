# apps/api/services/agent_runs/require_root_approval.py

"""Rejects public child approval mutations with a verified root reference."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.exceptions.general import ConflictError
from models.agent_run import AgentRun
from models.conversation import Conversation
from models.user import User
from models.workspace import Workspace


async def require_root_approval(
    db: AsyncSession, *, run: AgentRun, actor: User, workspace: Workspace
) -> None:
    """Requires the main run even when a specialist's parent is executing."""
    if run.parent_run_id is None and run.delegation_depth == 0:
        return
    root = await db.scalar(
        select(AgentRun)
        .join(Conversation, Conversation.id == AgentRun.conversation_id)
        .where(
            AgentRun.id == run.parent_run_id,
            AgentRun.parent_run_id.is_(None),
            AgentRun.delegation_depth == 0,
            AgentRun.workspace_id == workspace.id,
            AgentRun.user_id == actor.id,
            AgentRun.deleted.is_(False),
            Conversation.workspace_id == workspace.id,
            Conversation.user_id == actor.id,
            Conversation.deleted.is_(False),
        )
    )
    details = {"code": "delegated_run_requires_root_approval"}
    if root is not None:
        details.update(root_run_id=str(root.id), root_conversation_id=str(root.conversation_id))
    raise ConflictError(
        "Review these approvals in the main conversation.",
        conflicting_resource="agent_run",
        details=details,
    )
