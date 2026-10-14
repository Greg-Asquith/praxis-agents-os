# apps/api/services/files/ensure_source_file_folder.py

"""Resolve the durable output folder linked to an original File."""

from pathlib import PurePath
from typing import TYPE_CHECKING

from sqlalchemy import select

from models.files import File, FileFolder
from services.files.folder_utils import FOLDER_SOURCE_FILE_UNIQUE_INDEX, ensure_linked_folder

if TYPE_CHECKING:
    from services.agents.runtime.context import RuntimeDeps


async def ensure_source_file_folder(deps: "RuntimeDeps", source: File) -> FileFolder:
    """Returns the folder for a File's outputs, or the folder a derived File already sits in."""
    if source.folder_id is not None:
        current = await deps.db.scalar(
            select(FileFolder).where(
                FileFolder.id == source.folder_id,
                FileFolder.workspace_id == deps.workspace.id,
                FileFolder.source_file_id.is_not(None),
                FileFolder.deleted.is_(False),
            )
        )
        if current is not None:
            return current
    return await ensure_linked_folder(
        deps,
        link=FileFolder.source_file_id,
        link_id=source.id,
        link_index=FOLDER_SOURCE_FILE_UNIQUE_INDEX,
        name=PurePath(source.name).stem or source.name,
    )
