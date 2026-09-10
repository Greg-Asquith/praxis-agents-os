# apps/api/services/files/create_conversation_file_references.py

"""Create idempotent file references for a conversation."""

from collections.abc import Sequence
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from core.exceptions.general import NotFoundError
from models.files import File, FileReference
from services.files.visibility import visible_file_filter
from utils.content import ContentScope


async def create_conversation_file_references(
    db: AsyncSession,
    *,
    workspace_id: UUID,
    conversation_id: UUID,
    file_ids: Sequence[UUID],
    created_by_user_id: UUID,
) -> None:
    """Attach logical files to a conversation without duplicating existing references."""
    if not file_ids:
        return

    files = (
        await db.scalars(
            select(File).where(File.id.in_(file_ids), visible_file_filter(workspace_id))
        )
    ).all()
    files_by_id = {file.id: file for file in files}
    if any(file_id not in files_by_id for file_id in file_ids):
        raise NotFoundError("File not found", resource_type="file")

    rows = [
        {
            "id": uuid4(),
            "file_id": file_id,
            "workspace_id": workspace_id,
            "target_type": "conversation",
            "target_id": conversation_id,
            "file_revision_id": (
                files_by_id[file_id].published_revision_id
                if files_by_id[file_id].scope == ContentScope.PLATFORM
                else None
            ),
            "created_by_user_id": created_by_user_id,
        }
        for file_id in file_ids
    ]
    stmt = insert(FileReference).values(rows)
    stmt = stmt.on_conflict_do_nothing(
        index_elements=["file_id", "target_type", "target_id"],
    )
    await db.execute(stmt)
