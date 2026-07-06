# apps/api/services/files/write_agent_file.py

"""Create or edit an editable workspace file from an agent tool."""

from dataclasses import dataclass
from pathlib import PurePosixPath
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.exceptions.general import AppValidationError, ConflictError
from core.settings import settings
from models.agent import Agent
from models.files import File, FileRevision
from models.workspace import Workspace
from services.files.contract import FILE_CONTRACT, FileContractEntry, is_editable
from services.files.utils import (
    get_file_for_workspace,
    private_ref_from_key,
    revision_object_key,
    sha256_hex,
)
from services.storage.factory import get_storage_provider
from services.storage.paths import safe_filename


@dataclass(frozen=True)
class AgentFileWriteResult:
    """Result of an agent-authored file write."""

    file: File
    revision: FileRevision
    bytes_written: int


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

    if file_id is None:
        return await _create_agent_file(
            db,
            workspace=workspace,
            agent=agent,
            name=name,
            data=data,
            reject_existing_name=reject_existing_name,
        )
    return await _edit_agent_file(
        db,
        workspace=workspace,
        agent=agent,
        file_id=file_id,
        data=data,
        expected_current_revision_id=expected_current_revision_id,
    )


async def _create_agent_file(
    db: AsyncSession,
    *,
    workspace: Workspace,
    agent: Agent,
    name: str,
    data: bytes,
    reject_existing_name: bool,
) -> AgentFileWriteResult:
    filename, entry, extension = _editable_file_name_and_entry(name)
    if reject_existing_name:
        existing_id = await db.scalar(
            select(File.id).where(
                File.workspace_id == workspace.id,
                File.name == filename,
                File.deleted == False,  # noqa: E712
            )
        )
        if existing_id is not None:
            raise ConflictError(
                "A workspace file with this name already exists",
                conflicting_resource="file",
                details={"file_id": str(existing_id), "name": filename},
            )
    file_id = uuid4()
    revision_id = uuid4()
    object_key = revision_object_key(workspace.id, file_id, revision_id, extension)
    provider = get_storage_provider()
    stored = await provider.put_object(
        private_ref_from_key(object_key),
        data,
        content_type=entry.content_type,
    )
    content_hash = sha256_hex(data)
    file = File(
        id=file_id,
        workspace_id=workspace.id,
        name=filename,
        category=entry.category.value,
        content_type=entry.content_type,
        extension=extension,
        size_bytes=stored.size_bytes,
        content_hash=content_hash,
        revision_count=0,
        processing_status="ready",
        processing_attempts=0,
    )
    db.add(file)
    await db.flush()

    revision = FileRevision(
        id=revision_id,
        file_id=file.id,
        workspace_id=workspace.id,
        revision_number=1,
        revision_kind="create",
        content_type=entry.content_type,
        extension=extension,
        size_bytes=stored.size_bytes,
        content_hash=content_hash,
        object_key=object_key,
        created_by_agent_id=agent.id,
    )
    db.add(revision)
    await db.flush()

    file.current_revision_id = revision.id
    file.revision_count = revision.revision_number
    await db.flush()
    await db.refresh(file)
    return AgentFileWriteResult(file=file, revision=revision, bytes_written=len(data))


async def _edit_agent_file(
    db: AsyncSession,
    *,
    workspace: Workspace,
    agent: Agent,
    file_id: UUID,
    data: bytes,
    expected_current_revision_id: UUID | None,
) -> AgentFileWriteResult:
    file = await get_file_for_workspace(
        db,
        workspace=workspace,
        file_id=file_id,
        for_update=True,
    )
    if not is_editable(file.content_type):
        raise AppValidationError("File type does not support text edits", field="file_id")
    if expected_current_revision_id is None:
        raise AppValidationError(
            "expected_current_revision_id is required when editing a file",
            field="expected_current_revision_id",
        )
    if file.current_revision_id != expected_current_revision_id:
        raise ConflictError(
            "File has changed",
            conflicting_resource="file",
            details={"current_revision_id": str(file.current_revision_id)},
        )

    revision_id = uuid4()
    object_key = revision_object_key(workspace.id, file.id, revision_id, file.extension)
    provider = get_storage_provider()
    stored = await provider.put_object(
        private_ref_from_key(object_key),
        data,
        content_type=file.content_type,
    )
    content_hash = sha256_hex(data)
    revision = FileRevision(
        id=revision_id,
        file_id=file.id,
        workspace_id=workspace.id,
        revision_number=file.revision_count + 1,
        revision_kind="edit",
        content_type=file.content_type,
        extension=file.extension,
        size_bytes=stored.size_bytes,
        content_hash=content_hash,
        object_key=object_key,
        created_by_agent_id=agent.id,
    )
    db.add(revision)
    await db.flush()

    file.current_revision_id = revision.id
    file.revision_count = revision.revision_number
    file.size_bytes = revision.size_bytes
    file.content_hash = revision.content_hash
    file.processing_status = "ready"
    file.processing_error = None
    await db.flush()
    await db.refresh(file)
    return AgentFileWriteResult(file=file, revision=revision, bytes_written=len(data))


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
