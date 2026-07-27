# apps/api/services/memories/authorisation.py

"""Route-facing memory visibility and mutation authorization."""

from uuid import UUID

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from core.exceptions.auth import AuthorizationError
from core.exceptions.general import NotFoundError
from models.agent import Agent
from models.agent_memories import AgentMemory
from models.user import User
from models.workspace import Workspace, WorkspaceMembership
from services.memories.domain import MEMORY_SCOPE_USER, MEMORY_SCOPE_WORKSPACE
from services.workspaces.utils import EDITOR_ROLES, MANAGER_ROLES


def visible_memory_filter(
    *,
    workspace_id: UUID,
    user_id: UUID,
) -> ColumnElement[bool]:
    """Expose workspace/agent memories and only the caller's user memories."""
    return and_(
        AgentMemory.workspace_id == workspace_id,
        or_(
            AgentMemory.scope != MEMORY_SCOPE_USER,
            AgentMemory.user_id == user_id,
        ),
    )


async def get_visible_memory(
    db: AsyncSession,
    *,
    workspace: Workspace,
    user: User,
    memory_id: UUID,
    for_update: bool = False,
) -> AgentMemory:
    """Load one visible memory or return an indistinguishable miss."""
    stmt = select(AgentMemory).where(
        AgentMemory.id == memory_id,
        visible_memory_filter(workspace_id=workspace.id, user_id=user.id),
    )
    if for_update:
        stmt = stmt.with_for_update()
    memory = await db.scalar(stmt)
    if memory is None:
        raise NotFoundError(
            "Memory not found",
            resource_type="memory",
            resource_id=str(memory_id),
        )
    return memory


def ensure_can_edit_memory(
    memory: AgentMemory,
    *,
    membership: WorkspaceMembership,
    user: User,
) -> None:
    """Require member access and ownership of user-scoped memory."""
    if membership.role not in EDITOR_ROLES:
        raise AuthorizationError(
            "Requires higher level role",
            details={"allowed_roles": sorted(EDITOR_ROLES)},
        )
    if memory.scope == MEMORY_SCOPE_USER and memory.user_id != user.id:
        raise AuthorizationError("Memory not found or access denied")


def ensure_can_delete_memory(
    memory: AgentMemory,
    *,
    membership: WorkspaceMembership,
    user: User,
) -> None:
    """Require admin access for workspace scope and normal edit access otherwise."""
    ensure_can_edit_memory(memory, membership=membership, user=user)
    if memory.scope == MEMORY_SCOPE_WORKSPACE and membership.role not in MANAGER_ROLES:
        raise AuthorizationError(
            "Workspace memories can only be deleted by workspace managers",
            details={"allowed_roles": sorted(MANAGER_ROLES)},
        )


async def resolve_memory_agent(
    db: AsyncSession,
    *,
    workspace: Workspace,
    memory: AgentMemory,
) -> Agent:
    """Resolve the owning agent, or a stable workspace agent for shared scopes."""
    stmt = select(Agent).where(Agent.workspace_id == workspace.id)
    if memory.agent_id is not None:
        stmt = stmt.where(Agent.id == memory.agent_id)
    stmt = stmt.order_by(Agent.created_at, Agent.id).limit(1)
    agent = await db.scalar(stmt)
    if agent is None:
        raise NotFoundError(
            "Memory agent not found",
            resource_type="agent",
            resource_id=str(memory.agent_id) if memory.agent_id else None,
        )
    return agent
