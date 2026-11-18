# apps/api/services/email_suppressions/list_email_suppressions.py

"""List the workspace Do Not Email list."""

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from models.email_suppression import WorkspaceEmailSuppression
from models.user import User
from models.workspace import Workspace
from services.email_suppressions.schemas import EmailSuppressionListResponse
from services.email_suppressions.utils import suppression_read
from utils.pagination import paginate
from utils.search import contains_pattern


async def list_email_suppressions(
    db: AsyncSession,
    *,
    workspace: Workspace,
    search: str | None,
    limit: int,
    offset: int,
) -> EmailSuppressionListResponse:
    stmt = (
        select(WorkspaceEmailSuppression, User)
        .outerjoin(User, User.id == WorkspaceEmailSuppression.created_by_user_id)
        .where(WorkspaceEmailSuppression.workspace_id == workspace.id)
    )
    if search:
        pattern = contains_pattern(search)
        stmt = stmt.where(
            or_(
                WorkspaceEmailSuppression.email.ilike(pattern, escape="\\"),
                WorkspaceEmailSuppression.reason.ilike(pattern, escape="\\"),
            )
        )
    rows, total = await paginate(
        db,
        stmt,
        WorkspaceEmailSuppression.created_at.desc(),
        WorkspaceEmailSuppression.id,
        limit=limit,
        offset=offset,
        scalars=False,
    )
    return EmailSuppressionListResponse(
        entries=[suppression_read(entry, creator) for entry, creator in rows],
        total=total,
        limit=limit,
        offset=offset,
    )
