# apps/api/services/integrations/connections/list_connections.py

"""List connections visible in the acting workspace context."""

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from models.integrations import ExternalCredential, IntegrationConnection
from models.user import User
from models.workspace import Workspace, WorkspaceMembership
from services.integrations.connections.schemas import ConnectionListResponse
from services.integrations.connections.utils import build_connection_read
from services.workspaces.utils import MANAGER_ROLES


async def list_connections(
    db: AsyncSession,
    *,
    actor: User,
    workspace: Workspace,
    membership: WorkspaceMembership,
    limit: int,
    offset: int,
) -> ConnectionListResponse:
    visibility = (IntegrationConnection.owner_workspace_id == workspace.id) | (
        IntegrationConnection.owner_user_id == actor.id
    )
    filters = (IntegrationConnection.deleted.is_(False), visibility)
    total = await db.scalar(select(func.count()).select_from(IntegrationConnection).where(*filters))
    rows = (
        await db.execute(
            select(IntegrationConnection, ExternalCredential)
            .outerjoin(
                ExternalCredential,
                IntegrationConnection.credential_id == ExternalCredential.id,
            )
            .where(*filters)
            .order_by(IntegrationConnection.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
    ).all()
    include_credential = membership.role in MANAGER_ROLES
    return ConnectionListResponse(
        items=[
            build_connection_read(
                connection,
                credential,
                include_credential=include_credential,
            )
            for connection, credential in rows
        ],
        total=total or 0,
        limit=limit,
        offset=offset,
    )
