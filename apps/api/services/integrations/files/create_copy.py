# apps/api/services/integrations/files/create_copy.py

"""Creates workspace File copies through the shared storage lifecycle."""

from pathlib import PurePosixPath
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from core.exceptions.general import AppValidationError
from models.agent import Agent
from models.user import User
from models.workspace import Workspace
from services.files import create_conversation_file_references, resolve_folder_by_name
from services.files.contract import contract_for_content_type
from services.files.create_file_with_revision import (
    FileRevisionWriteResult,
    create_file_with_revision,
)
from services.files.reserve_file_revision import reserve_file_revision
from services.files.revision_actor import FileRevisionActor
from services.files.utils import sha256_hex
from services.storage.paths import safe_filename
from utils.validation import normalize_optional_text


async def create_copy(
    db: AsyncSession,
    *,
    workspace: Workspace,
    user: User,
    conversation_id: UUID,
    name: str,
    content: bytes,
    content_type: str,
    agent: Agent | None = None,
    folder: str | None = None,
) -> FileRevisionWriteResult:
    """Reserves, creates, and links a File within the caller's audited transaction.

    The agent is the revision actor when given; otherwise the person is. Folders are
    resolved by name only for agents, so a person's copy lands at the Files root.
    """
    contract = contract_for_content_type(content_type)
    name = safe_filename(name)[:255]
    extension = PurePosixPath(name).suffix.lower()
    if extension not in contract.extensions:
        extension = contract.extensions[0]
        name = f"{name[: 255 - len(extension)]}{extension}"
    folder_name = normalize_optional_text(folder)
    if folder_name is not None and agent is None:
        raise AppValidationError("Only an agent can save a copy into a folder by name")
    reservation = await reserve_file_revision(
        db,
        workspace_id=workspace.id,
        user_id=user.id,
        name=name,
        size_bytes=len(content),
        content_hash=sha256_hex(content),
        content_type=contract.content_type,
        extension=extension,
    )
    target_folder = (
        await resolve_folder_by_name(
            db, workspace=workspace, agent=agent, requested_by=user, name=folder_name
        )
        if folder_name is not None
        else None
    )
    saved = await create_file_with_revision(
        db,
        workspace=workspace,
        name=name,
        content=content,
        content_type=contract.content_type,
        extension=extension,
        actor=FileRevisionActor(agent_id=agent.id)
        if agent is not None
        else FileRevisionActor(user_id=user.id),
        resolved_folder=target_folder,
        reservation=reservation,
    )
    await create_conversation_file_references(
        db,
        workspace_id=workspace.id,
        conversation_id=conversation_id,
        file_ids=[saved.file.id],
        created_by_user_id=user.id,
    )
    return saved
