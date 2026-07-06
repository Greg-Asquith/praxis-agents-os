# apps/api/services/files/get_file.py

"""Fetch one workspace file."""

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from models.workspace import Workspace
from services.files.domain import FileRead
from services.files.utils import file_to_read, get_file_for_workspace


async def get_file(
    db: AsyncSession,
    *,
    workspace: Workspace,
    file_id: UUID,
) -> FileRead:
    """Return one non-deleted workspace file."""
    file = await get_file_for_workspace(db, workspace=workspace, file_id=file_id)
    return file_to_read(file)
