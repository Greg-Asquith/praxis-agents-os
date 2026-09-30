# apps/api/services/agents/builtin/create_builtin_agent.py

"""Create the built-in agent for a new workspace."""

from sqlalchemy.ext.asyncio import AsyncSession

from models.agent import Agent
from models.user import User
from models.workspace import Workspace
from services.agents.builtin.identity import (
    BUILTIN_AGENT_DESCRIPTION,
    BUILTIN_AGENT_IDENTITY_COLOR,
    BUILTIN_AGENT_SLUG,
)
from services.audit_events import AuditAction, AuditResourceType
from services.audit_events.workspace_events import record_workspace_audit_event


async def create_builtin_agent(db: AsyncSession, *, workspace: Workspace, owner: User) -> Agent:
    """Creates the built-in agent in a workspace created in this transaction.

    Existing workspaces received theirs from migration `core_0063`. The caller
    must have set the workspace tenant context, because row-level security
    rejects agent inserts otherwise.

    Args:
        workspace: The new workspace, which has no agents yet.
        owner: The workspace owner, recorded as the agent's creator.

    Returns:
        The created built-in agent.
    """
    agent = Agent(
        slug=BUILTIN_AGENT_SLUG,
        description=BUILTIN_AGENT_DESCRIPTION,
        instructions="",
        workspace_id=workspace.id,
        created_by=owner.id,
        is_builtin=True,
        all_tools=True,
        metadata_json={"identity_color": BUILTIN_AGENT_IDENTITY_COLOR},
    )
    db.add(agent)
    await db.flush([agent])
    await record_workspace_audit_event(
        db,
        request=None,
        workspace_id=workspace.id,
        action=AuditAction.CREATE,
        resource_type=AuditResourceType.AGENT,
        resource_id=agent.id,
        actor=owner,
        details={"slug": agent.slug, "builtin": True},
    )
    return agent
