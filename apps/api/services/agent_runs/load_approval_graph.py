"""Loads the actor-scoped approval graph without changing suspended state."""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.exceptions.general import NotFoundError
from models.agent_run import AgentRun
from models.conversation import Conversation
from models.user import User
from models.workspace import Workspace
from services.agent_runs.domain import RUN_STATUS_AWAITING_APPROVAL
from services.agents.delegation_approval import DELEGATED_APPROVAL_KIND
from services.agents.runtime.approval_identity import MAX_PROJECTION_LEAVES, invalid_approval_state
from services.agents.runtime.approval_projection import (
    ApprovalGraph,
    build_approval_graph,
    delegated_child_id,
)
from services.agents.runtime.approval_state import load_suspended_run_state


async def load_approval_graph(
    db: AsyncSession, *, actor: User, workspace: Workspace, run_id: UUID
) -> ApprovalGraph:
    """Validates canonical ownership and retains unavailable child classifications."""
    # Disable autoflush so repeated legacy reads cannot persist unrelated state.
    with db.no_autoflush:
        root = await db.scalar(
            select(AgentRun).where(
                AgentRun.id == run_id,
                AgentRun.workspace_id == workspace.id,
                AgentRun.user_id == actor.id,
                AgentRun.deleted == False,  # noqa: E712
            )
        )
        if root is None:
            raise NotFoundError(
                "Agent run not found", resource_type="agent_run", resource_id=str(run_id)
            )
        if root.status != RUN_STATUS_AWAITING_APPROVAL:
            raise invalid_approval_state("The root run is not awaiting approval")
        await _validate_conversation(db, root)
        suspended = load_suspended_run_state(root)
        if len(suspended.deferred_tool_requests.approvals) > MAX_PROJECTION_LEAVES:
            raise invalid_approval_state("Saved approval state has too many calls")
        child_ids = {
            child_id
            for call in suspended.deferred_tool_requests.approvals
            if (metadata := suspended.deferred_tool_requests.metadata.get(call.tool_call_id))
            is not None
            if metadata.get("kind") == DELEGATED_APPROVAL_KIND
            and (child_id := delegated_child_id(metadata)) is not None
        }
        children: dict[UUID, AgentRun] = {}
        if child_ids:
            rows = await db.scalars(
                select(AgentRun).where(
                    AgentRun.id.in_(child_ids),
                    AgentRun.workspace_id == workspace.id,
                    AgentRun.user_id == actor.id,
                    AgentRun.deleted == False,  # noqa: E712
                )
            )
            for child in rows:
                await _validate_conversation(db, child)
                children[child.id] = child
        return build_approval_graph(root, children)


async def _validate_conversation(db: AsyncSession, run: AgentRun) -> None:
    conversation = await db.scalar(
        select(Conversation).where(
            Conversation.id == run.conversation_id,
            Conversation.workspace_id == run.workspace_id,
            Conversation.user_id == run.user_id,
            Conversation.deleted == False,  # noqa: E712
        )
    )
    if conversation is None or (
        conversation.active_agent_id is not None and conversation.active_agent_id != run.agent_id
    ):
        raise invalid_approval_state("Saved approval conversation is unavailable")
