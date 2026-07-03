# apps/api/services/skills/documents/confirm_document_upload.py

"""Confirm an uploaded skill document and store its markdown conversion."""

from uuid import UUID

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

from core.exceptions.general import AppValidationError
from models.user import User
from models.workspace import Workspace, WorkspaceMembership
from services.assets.domain import AssetKind
from services.assets.tokens import token_ref, verify_asset_upload_token
from services.assets.utils import validate_stored_object
from services.audit_events import AuditAction, AuditResourceType
from services.audit_events.workspace_events import record_workspace_audit_event
from services.skills.documents.domain import (
    SkillDocumentConfirmRequest,
    SkillDocumentConversionError,
    SkillDocumentEntry,
    SkillDocumentRead,
)
from services.skills.documents.utils import (
    allowed_document_content_types,
    best_effort_delete_private_object,
    convert_document_to_markdown,
    manifest_now,
    markdown_ref_for_original,
    parse_skill_doc_key,
)
from services.skills.utils import get_skill_for_workspace, require_skill_write_access
from services.storage.domain import StorageBucket
from services.storage.factory import get_storage_provider


async def confirm_skill_document_upload(
    db: AsyncSession,
    *,
    request: Request,
    actor: User,
    workspace: Workspace,
    membership: WorkspaceMembership,
    skill_id: UUID,
    payload: SkillDocumentConfirmRequest,
) -> SkillDocumentRead:
    """Confirm a private skill document upload and update the skill manifest."""
    require_skill_write_access(membership)
    skill = await get_skill_for_workspace(db, workspace=workspace, skill_id=skill_id)
    token_payload = verify_asset_upload_token(
        payload.upload_token,
        expected_kind=AssetKind.SKILL_DOCUMENT,
        actor_user_id=actor.id,
        workspace_id=workspace.id,
    )
    ref = token_ref(token_payload)
    if ref.bucket != StorageBucket.PRIVATE:
        raise AppValidationError("Upload token is not valid for this skill", field="upload_token")

    parsed_key = parse_skill_doc_key(ref.key)
    if parsed_key.workspace_id != workspace.id or parsed_key.skill_id != skill.id:
        raise AppValidationError("Upload token is not valid for this skill", field="upload_token")
    document_name = parsed_key.document_name
    filename = parsed_key.filename

    provider = get_storage_provider()
    stored = validate_stored_object(
        await provider.stat_object(ref),
        expected_content_type=token_payload.content_type,
        allowed_content_types=allowed_document_content_types(),
        max_size_bytes=token_payload.max_size_bytes,
        asset_label="skill document",
    )
    data = await provider.get_object(ref)
    markdown_object_key: str | None = None
    markdown_size_bytes: int | None = None
    status = "ready"
    error: str | None = None

    try:
        markdown = await convert_document_to_markdown(
            data,
            content_type=token_payload.content_type,
            filename=filename,
        )
        markdown_storage_ref = markdown_ref_for_original(ref)
        await provider.put_object(
            markdown_storage_ref,
            markdown.encode("utf-8"),
            content_type="text/markdown",
        )
        markdown_object_key = markdown_storage_ref.key
        markdown_size_bytes = len(markdown.encode("utf-8"))
    except SkillDocumentConversionError as exc:
        status = "failed"
        error = exc.message

    manifest = dict(skill.documentation_refs or {})
    previous_entry = manifest.get(document_name)
    entry = SkillDocumentEntry(
        original=ref.key,
        markdown=markdown_object_key,
        filename=filename,
        content_type=stored.content_type or token_payload.content_type,
        size_bytes=stored.size_bytes,
        markdown_size_bytes=markdown_size_bytes,
        status=status,
        error=error,
        updated_at=stored.updated_at or manifest_now(),
    )
    manifest[document_name] = entry.model_dump(mode="json")
    skill.documentation_refs = manifest
    await db.flush()

    await _delete_replaced_objects(previous_entry, entry, provider=provider)
    await record_workspace_audit_event(
        db,
        request=request,
        workspace_id=workspace.id,
        action=AuditAction.UPDATE,
        resource_type=AuditResourceType.SKILL,
        resource_id=skill.id,
        actor=actor,
        details={"document": document_name, "action": "upload", "status": entry.status},
    )
    await db.refresh(skill)
    return SkillDocumentRead(name=document_name, **entry.model_dump())


async def _delete_replaced_objects(
    previous_entry: object,
    entry: SkillDocumentEntry,
    *,
    provider,
) -> None:
    if not isinstance(previous_entry, dict):
        return
    previous_original = previous_entry.get("original")
    previous_markdown = previous_entry.get("markdown")
    if isinstance(previous_original, str) and previous_original != entry.original:
        await best_effort_delete_private_object(previous_original, provider=provider)
    if isinstance(previous_markdown, str) and previous_markdown != entry.markdown:
        await best_effort_delete_private_object(previous_markdown, provider=provider)
