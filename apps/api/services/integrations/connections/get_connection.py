# apps/api/services/integrations/connections/get_connection.py

"""Read one visible connection with role-filtered credential metadata."""

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from models.user import User
from models.workspace import Workspace, WorkspaceMembership
from services.integrations.connections.schemas import ConnectionRead
from services.integrations.connections.utils import connection_to_read, get_visible_connection
from services.workspaces.utils import MANAGER_ROLES


async def get_connection(
    db: AsyncSession,
    *,
    connection_id: UUID,
    actor: User,
    workspace: Workspace,
    membership: WorkspaceMembership,
) -> ConnectionRead:
    connection = await get_visible_connection(
        db, connection_id=connection_id, actor=actor, workspace=workspace
    )
    return await connection_to_read(
        db,
        connection,
        include_credential=membership.role in MANAGER_ROLES,
    )
