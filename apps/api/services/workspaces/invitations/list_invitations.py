# apps/api/services/workspaces/invitations/list_invitations.py

"""List invitations for a workspace."""

from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from models.user import User
from models.workspace import WorkspaceInvitation
from services.workspaces.schemas import (
    WorkspaceInvitationRead,
    WorkspaceInvitationsListResponse,
)
from services.workspaces.utils import MANAGER_ROLES, require_workspace_role
from utils.pagination import paginate


async def list_invitations(
    db: AsyncSession,
    *,
    actor: User,
    workspace_id: UUID,
    include_accepted: bool,
    include_expired: bool,
    limit: int,
    offset: int,
) -> WorkspaceInvitationsListResponse:
    await require_workspace_role(
        db,
        actor=actor,
        workspace_id=workspace_id,
        allowed_roles=MANAGER_ROLES,
    )
    stmt = select(WorkspaceInvitation).where(
        WorkspaceInvitation.workspace_id == workspace_id,
        WorkspaceInvitation.deleted.is_(False),
    )
    if not include_accepted:
        stmt = stmt.where(WorkspaceInvitation.accepted_at.is_(None))
    if not include_expired:
        stmt = stmt.where(WorkspaceInvitation.expires_at > func.now())

    invitations, total = await paginate(
        db,
        stmt,
        WorkspaceInvitation.created_at.desc(),
        limit=limit,
        offset=offset,
    )
    return WorkspaceInvitationsListResponse(
        invitations=[
            WorkspaceInvitationRead.from_invitation(invitation) for invitation in invitations
        ],
        total=total or 0,
        limit=limit,
        offset=offset,
    )
