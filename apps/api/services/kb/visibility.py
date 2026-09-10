# apps/api/services/kb/visibility.py

"""Knowledge visibility for ORM reads and the chunk-search SQL aliases."""

from uuid import UUID

from sqlalchemy import and_, false, or_, select
from sqlalchemy.sql.elements import ColumnElement

from models.kb import KBChunk, KBDocument


def visible_document_filter(
    workspace_id: UUID | None,
    user_id: UUID | None,
    *,
    private_only: bool = False,
    include_unready_local_sources: bool = False,
) -> ColumnElement[bool]:
    """Preserves local privacy and source access when admitting platform knowledge."""
    if workspace_id is None:
        return false()
    local = and_(
        KBDocument.scope == "workspace",
        KBDocument.workspace_id == workspace_id,
        or_(
            KBDocument.is_private.is_(False),
            KBDocument.created_by_user_id == user_id if user_id is not None else false(),
        ),
    )
    ownership = (
        and_(local, KBDocument.is_private.is_(True))
        if private_only
        else or_(
            local,
            and_(
                KBDocument.scope == "platform",
                KBDocument.workspace_id.is_(None),
                KBDocument.is_published.is_(True),
                KBDocument.is_private.is_(False),
            ),
        )
    )
    return and_(
        KBDocument.deleted.is_(False),
        KBDocument.deleted_at.is_(None),
        or_(
            KBDocument.source_type.not_in(("url", "integration")),
            KBDocument.source_sync_status == "ready",
            KBDocument.scope == "workspace" if include_unready_local_sources else false(),
        ),
        ownership,
    )


def visible_chunk_filter(
    workspace_id: UUID | None, user_id: UUID | None, *, private_only: bool = False
) -> ColumnElement[bool]:
    """Requires chunk ownership to match a visible document."""
    return (
        select(KBDocument.id)
        .where(
            KBDocument.id == KBChunk.document_id,
            KBChunk.scope == KBDocument.scope,
            KBChunk.workspace_id.is_not_distinct_from(KBDocument.workspace_id),
            visible_document_filter(workspace_id, user_id, private_only=private_only),
        )
        .correlate(KBChunk)
        .exists()
    )


# Aliases and bound parameters match the shared chunk search.
VISIBLE_CHUNK_SQL = """
    :workspace_id IS NOT NULL
    AND c.document_id = d.id
    AND c.scope = d.scope
    AND c.workspace_id IS NOT DISTINCT FROM d.workspace_id
    AND NOT d.deleted AND d.deleted_at IS NULL
    AND (d.source_type NOT IN ('url', 'integration') OR d.source_sync_status = 'ready')
    AND (
        (d.scope = 'workspace' AND d.workspace_id = :workspace_id
         AND (NOT d.is_private OR d.created_by_user_id = :user_id)
         AND (NOT :private_only OR d.is_private))
        OR
        (d.scope = 'platform' AND d.workspace_id IS NULL AND d.is_published
         AND NOT d.is_private AND NOT :private_only)
    )
"""
