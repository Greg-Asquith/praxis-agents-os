# apps/api/services/integrations/files/create_copy.py

"""Creates workspace File copies through the shared storage lifecycle."""

from pathlib import PurePosixPath

from services.agents.runtime.context import RuntimeDeps
from services.files import create_conversation_file_references, resolve_folder_by_name
from services.files.contract import contract_for_content_type
from services.files.create_file_with_revision import (
    FileRevisionWriteResult,
    create_file_with_revision,
)
from services.files.reserve_file_revision import reserve_file_revision
from services.files.revision_actor import FileRevisionActor
from services.storage.paths import safe_filename
from utils.validation import normalize_optional_text


async def create_copy(
    deps: RuntimeDeps,
    *,
    name: str,
    content: bytes,
    content_type: str,
    folder: str | None = None,
) -> FileRevisionWriteResult:
    """Reserves, creates, and links a File within the caller's audited transaction."""
    contract = contract_for_content_type(content_type)
    name = safe_filename(name)[:255]
    extension = PurePosixPath(name).suffix.lower()
    if extension not in contract.extensions:
        extension = contract.extensions[0]
        name = f"{name[: 255 - len(extension)]}{extension}"
    folder_name = normalize_optional_text(folder)
    reservation = await reserve_file_revision(
        deps.db,
        workspace_id=deps.workspace.id,
        user_id=deps.user.id,
        name=name,
        content=content,
        content_type=contract.content_type,
        extension=extension,
    )
    target_folder = (
        await resolve_folder_by_name(
            deps.db,
            workspace=deps.workspace,
            agent=deps.agent,
            requested_by=deps.user,
            name=folder_name,
        )
        if folder_name is not None
        else None
    )
    saved = await create_file_with_revision(
        deps.db,
        workspace=deps.workspace,
        name=name,
        content=content,
        content_type=contract.content_type,
        extension=extension,
        actor=FileRevisionActor(agent_id=deps.agent.id),
        resolved_folder=target_folder,
        reservation=reservation,
    )
    await create_conversation_file_references(
        deps.db,
        workspace_id=deps.workspace.id,
        conversation_id=deps.conversation.id,
        file_ids=[saved.file.id],
        created_by_user_id=deps.user.id,
    )
    return saved
