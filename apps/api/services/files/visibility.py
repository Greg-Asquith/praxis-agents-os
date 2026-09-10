# apps/api/services/file/visibility.py

"""Read predicates for local and published platform Files."""

from uuid import UUID

from sqlalchemy import and_, false, or_, select
from sqlalchemy.sql.elements import ColumnElement

from models.files import File, FileRevision


def visible_file_filter(workspace_id: UUID | None) -> ColumnElement[bool]:
    """Returns visible parents, excluding drafts, withdrawals, and deletions."""
    if workspace_id is None:
        return false()
    return and_(
        File.deleted.is_(False),
        or_(
            and_(File.scope == "workspace", File.workspace_id == workspace_id),
            and_(
                File.scope == "platform",
                File.workspace_id.is_(None),
                File.is_published.is_(True),
            ),
        ),
    )


def visible_file_revision_filter(workspace_id: UUID | None) -> ColumnElement[bool]:
    """Requires a visible parent, matching ownership, and a reviewed revision."""
    return (
        select(File.id)
        .where(
            File.id == FileRevision.file_id,
            visible_file_filter(workspace_id),
            FileRevision.scope == File.scope,
            FileRevision.workspace_id.is_not_distinct_from(File.workspace_id),
            or_(File.scope == "workspace", FileRevision.is_published.is_(True)),
        )
        .correlate(FileRevision)
        .exists()
    )
