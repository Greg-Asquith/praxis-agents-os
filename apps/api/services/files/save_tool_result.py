# apps/api/services/files/save_tool_result.py

"""Retains complete tool results without adding documents to the Files listing."""

from __future__ import annotations

from typing import TYPE_CHECKING

from core.exceptions.general import AppValidationError
from core.settings import settings
from services.audit_events import AuditAction, AuditActorType, AuditResourceType
from services.audit_events.operations import safe_record_operation_audit_event
from services.files.contract import contract_for_content_type, max_size_bytes
from services.files.create_conversation_file_references import create_conversation_file_references
from services.files.create_file_with_revision import (
    FileRevisionWriteResult,
    create_file_with_revision,
)
from services.files.revision_actor import FileRevisionActor

if TYPE_CHECKING:
    from services.agents.runtime.context import RuntimeDeps


async def save_tool_result(
    deps: RuntimeDeps,
    *,
    tool_name: str,
    tool_call_id: str,
    name: str,
    content: bytes,
) -> FileRevisionWriteResult:
    """Saves an internal JSON snapshot inside the caller's transaction."""
    maximum = min(
        settings.MAX_FILE_SIZE_AGENT_FILE,
        max_size_bytes(contract_for_content_type("application/json")),
    )
    if len(content) > maximum:
        raise AppValidationError(
            f"Tool result contains {len(content):,} bytes; the storage limit is {maximum:,} bytes. "
            "Narrow the query and try again.",
            field="result",
        )
    saved = await create_file_with_revision(
        deps.db,
        workspace=deps.workspace,
        name=name,
        content=content,
        content_type="application/json",
        extension=".json",
        actor=FileRevisionActor(agent_id=deps.agent.id),
    )
    saved.file.is_tool_result = True
    await deps.db.flush()
    await create_conversation_file_references(
        deps.db,
        workspace_id=deps.workspace.id,
        conversation_id=deps.conversation.id,
        file_ids=[saved.file.id],
        created_by_user_id=deps.user.id,
    )
    await safe_record_operation_audit_event(
        deps.db,
        workspace_id=deps.workspace.id,
        action=AuditAction.CREATE,
        resource_type=AuditResourceType.FILE,
        resource_id=saved.file.id,
        actor_type=AuditActorType.AGENT,
        actor_id=deps.agent.id,
        actor_display=deps.agent.name,
        requested_by_user_id=deps.user.id,
        details={
            "source": "tool_result",
            "run_id": str(deps.run.id),
            "conversation_id": str(deps.conversation.id),
            "tool_name": tool_name,
            "tool_call_id": tool_call_id,
            "revision_id": str(saved.revision.id),
            "size_bytes": saved.bytes_written,
            "content_hash": saved.revision.content_hash,
        },
    )
    return saved
