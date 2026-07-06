# apps/api/services/scratch/upsert_scratch_entry.py

"""Create or overwrite one scratch entry."""

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from core.exceptions.general import AppValidationError
from core.settings import settings
from models.scratch import ScratchEntry
from services.scratch.domain import ScratchScope, validate_scratch_name
from services.scratch.utils import scope_filters, scope_values, scratch_expires_at


async def upsert_scratch_entry(
    db: AsyncSession,
    *,
    workspace_id: UUID,
    scope: ScratchScope,
    name: str,
    content: str,
    created_by_run_id: UUID | None,
) -> ScratchEntry:
    """Create or overwrite a scratch entry in one scope."""
    normalized_name = validate_scratch_name(name)
    content_bytes = len(content.encode("utf-8"))
    if content_bytes > settings.SCRATCH_MAX_ENTRY_BYTES:
        raise AppValidationError(
            "Scratch entry is too large",
            field="content",
            details={
                "max_bytes": settings.SCRATCH_MAX_ENTRY_BYTES,
                "content_bytes": content_bytes,
            },
        )

    now = datetime.now(UTC)
    existing = await _get_entry(db, workspace_id=workspace_id, scope=scope, name=normalized_name)
    is_active_overwrite = existing is not None and existing.expires_at > now
    if not is_active_overwrite:
        count = await db.scalar(
            select(func.count())
            .select_from(ScratchEntry)
            .where(
                ScratchEntry.workspace_id == workspace_id,
                ScratchEntry.expires_at > now,
                *scope_filters(scope),
            )
        )
        if int(count or 0) >= settings.SCRATCH_MAX_ENTRIES_PER_SCOPE:
            raise AppValidationError(
                "Scratch scope has too many entries",
                field="name",
                details={"max_entries": settings.SCRATCH_MAX_ENTRIES_PER_SCOPE},
            )

    expires_at = scratch_expires_at(now=now)
    values = {
        "workspace_id": workspace_id,
        **scope_values(scope),
        "name": normalized_name,
        "content": content,
        "content_bytes": content_bytes,
        "expires_at": expires_at,
        "created_by_run_id": created_by_run_id,
        "updated_at": now,
    }
    stmt = insert(ScratchEntry).values(**values)
    if scope.conversation_id is not None:
        stmt = stmt.on_conflict_do_update(
            index_elements=[ScratchEntry.conversation_id, ScratchEntry.name],
            index_where=ScratchEntry.conversation_id.is_not(None),
            set_={
                "content": content,
                "content_bytes": content_bytes,
                "expires_at": expires_at,
                "created_by_run_id": created_by_run_id,
                "updated_at": now,
            },
        )
    else:
        stmt = stmt.on_conflict_do_update(
            index_elements=[ScratchEntry.run_id, ScratchEntry.name],
            index_where=ScratchEntry.run_id.is_not(None),
            set_={
                "content": content,
                "content_bytes": content_bytes,
                "expires_at": expires_at,
                "created_by_run_id": created_by_run_id,
                "updated_at": now,
            },
        )
    await db.execute(stmt)
    await db.flush()

    if existing is not None:
        await db.refresh(existing)
        return existing

    entry = await _get_entry(db, workspace_id=workspace_id, scope=scope, name=normalized_name)
    if entry is None:
        raise RuntimeError("Scratch entry upsert did not return a readable row")
    return entry


async def _get_entry(
    db: AsyncSession,
    *,
    workspace_id: UUID,
    scope: ScratchScope,
    name: str,
) -> ScratchEntry | None:
    return await db.scalar(
        select(ScratchEntry).where(
            ScratchEntry.workspace_id == workspace_id,
            ScratchEntry.name == name,
            *scope_filters(scope),
        )
    )
