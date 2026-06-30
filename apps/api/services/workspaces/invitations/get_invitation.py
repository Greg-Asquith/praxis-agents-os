# apps/api/services/workspaces/invitations/get_invitation.py

"""Read one workspace invitation."""

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from models.user import User
from services.workspaces.invitations.utils import get_invitation_or_raise
from services.workspaces.schemas import WorkspaceInvitationRead
from services.workspaces.utils import MANAGER_ROLES, require_workspace_role


async def get_invitation(
    db: AsyncSession,
    *,
    actor: User,
    workspace_id: UUID,
    invitation_id: UUID,
) -> WorkspaceInvitationRead:
    await require_workspace_role(
        db,
        actor=actor,
        workspace_id=workspace_id,
        allowed_roles=MANAGER_ROLES,
    )
    invitation = await get_invitation_or_raise(
        db,
        workspace_id=workspace_id,
        invitation_id=invitation_id,
    )
    return WorkspaceInvitationRead.from_invitation(invitation)
