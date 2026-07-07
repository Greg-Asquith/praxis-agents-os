# apps/api/services/files/create_conversation_file_references.py

"""Create idempotent file references for a conversation."""

from collections.abc import Sequence
from uuid import UUID, uuid4

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from models.files import FileReference


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

    rows = [
        {
            "id": uuid4(),
            "file_id": file_id,
            "workspace_id": workspace_id,
            "target_type": "conversation",
            "target_id": conversation_id,
            "file_revision_id": None,
            "created_by_user_id": created_by_user_id,
        }
        for file_id in file_ids
    ]
    stmt = insert(FileReference).values(rows)
    stmt = stmt.on_conflict_do_nothing(
        index_elements=["file_id", "target_type", "target_id"],
    )
    await db.execute(stmt)
