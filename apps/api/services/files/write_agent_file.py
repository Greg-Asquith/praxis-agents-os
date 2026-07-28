# apps/api/services/files/write_agent_file.py

"""Create or edit an editable workspace file from an agent tool."""

from pathlib import PurePosixPath
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.exceptions.general import AppValidationError, ConflictError
from core.settings import settings
from models.agent import Agent
from models.files import File
from models.workspace import Workspace
from services.files.append_file_revision import append_file_revision
from services.files.contract import FILE_CONTRACT, FileContractEntry, is_editable
from services.files.create_file_with_revision import (
    FileRevisionWriteResult as AgentFileWriteResult,
    create_file_with_revision,
)
from services.files.revision_actor import FileRevisionActor
from services.files.utils import get_file_for_workspace
from services.storage.paths import safe_filename


async def write_agent_file(
    db: AsyncSession,
    *,
    workspace: Workspace,
    agent: Agent,
    name: str,
    content: str,
    file_id: UUID | None = None,
    expected_current_revision_id: UUID | None = None,
    reject_existing_name: bool = False,
) -> AgentFileWriteResult:
    """Create an editable text file or append an editable text revision."""
    data = content.encode("utf-8")
    if len(data) > settings.MAX_FILE_SIZE_AGENT_FILE:
        raise AppValidationError(
            "Agent-created file content is too large",
            field="content",
            details={
                "max_bytes": settings.MAX_FILE_SIZE_AGENT_FILE,
                "content_bytes": len(data),
            },
        )
    actor = FileRevisionActor(agent_id=agent.id)
    if file_id is None:
        filename, entry, extension = _editable_file_name_and_entry(name)
        if reject_existing_name:
            existing_id = await db.scalar(
                select(File.id).where(
                    File.workspace_id == workspace.id,
                    File.name == filename,
                    File.deleted.is_(False),
                )
            )
            if existing_id is not None:
                raise ConflictError(
                    "A workspace file with this name already exists",
                    conflicting_resource="file",
                    details={"file_id": str(existing_id), "name": filename},
                )
        return await create_file_with_revision(
            db,
            workspace=workspace,
            name=filename,
            content=data,
            content_type=entry.content_type,
            extension=extension,
            actor=actor,
        )

    file = await get_file_for_workspace(db, workspace=workspace, file_id=file_id)
    if not is_editable(file.content_type):
        raise AppValidationError("File type does not support text edits", field="file_id")
    if expected_current_revision_id is None:
        raise AppValidationError(
            "expected_current_revision_id is required when editing a file",
            field="expected_current_revision_id",
        )
    return await append_file_revision(
        db,
        workspace=workspace,
        file_id=file.id,
        content=data,
        actor=actor,
        expected_current_revision_id=expected_current_revision_id,
    )


def _editable_file_name_and_entry(name: str) -> tuple[str, FileContractEntry, str]:
    filename = safe_filename(name)
    extension = PurePosixPath(filename).suffix.lower()
    if not extension:
        filename = f"{filename}.md"
        extension = ".md"
    for entry in FILE_CONTRACT:
        if entry.editable and extension in entry.extensions:
            return filename, entry, extension
    raise AppValidationError(
        "Agent file writes support editable text filenames only",
        field="name",
    )
