# apps/api/services/files/get_file.py

"""Fetch one workspace file."""

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from models.workspace import Workspace
from services.files.domain import FileRead
from services.files.utils import (
    file_for_revision,
    file_to_read,
    get_file_folder_name,
    get_visible_file,
    get_visible_file_revision,
)


async def get_file(
    db: AsyncSession,
    *,
    workspace: Workspace,
    file_id: UUID,
) -> FileRead:
    """Return one non-deleted workspace file."""
    file = await get_visible_file(db, workspace_id=workspace.id, file_id=file_id)
    revision = await get_visible_file_revision(db, workspace_id=workspace.id, file=file)
    return file_to_read(
        file_for_revision(file, revision),
        folder_name=await get_file_folder_name(db, workspace=workspace, file=file),
    )
