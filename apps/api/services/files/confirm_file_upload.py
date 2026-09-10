# apps/api/services/files/confirm_file_upload.py

"""Confirms workspace uploads and authorised platform drafts."""

from datetime import UTC, datetime
from pathlib import PurePosixPath

from fastapi import Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import maintenance_async_db_session
from core.dependencies import require_super_admin_user
from core.exceptions.general import AppValidationError, ConflictError
from models.files import File, FileRevision, FileUpload
from models.user import User
from models.workspace import Workspace, WorkspaceMembership
from services.assets.domain import AssetKind
from services.assets.tokens import token_ref, verify_asset_upload_token
from services.assets.utils import validate_stored_object
from services.audit_events import AuditAction, AuditResourceType
from services.audit_events.platform_content_events import (
    PlatformContentAuditDetails,
    record_platform_content_audit_event,
)
from services.audit_events.workspace_events import record_workspace_audit_event
from services.files.contract import FILE_CONTRACT, require_matching_pair
from services.files.domain import FileConfirmRequest, FileRead
from services.files.utils import (
    best_effort_delete_file_object,
    file_storage_bucket,
    file_storage_prefix,
    file_to_read,
    get_file_folder_name,
    get_file_for_upload,
    get_folder_for_workspace,
    require_declared_upload_size,
    require_file_write_access,
    set_processing_state_for_revision,
    sha256_hex_stream,
)
from services.storage.domain import make_storage_object_ref
from services.storage.factory import get_storage_provider
from services.storage.utils import promote_object_or_get_existing
from utils.content import ContentScope


async def confirm_file_upload(
    db: AsyncSession,
    *,
    request: Request,
    actor: User,
    workspace: Workspace,
    membership: WorkspaceMembership,
    payload: FileConfirmRequest,
    scope: ContentScope = ContentScope.WORKSPACE,
) -> FileRead:
    """Confirms an uploaded file and appends an immutable revision."""
    scope = ContentScope(scope)
    if scope == ContentScope.PLATFORM:
        require_super_admin_user(actor)
        if payload.folder_id is not None:
            raise AppValidationError("Platform files cannot belong to a folder", field="folder_id")
        await db.commit()
        async with maintenance_async_db_session() as maintenance_db:
            return await _confirm_upload(
                maintenance_db,
                request=request,
                actor=actor,
                workspace=None,
                payload=payload,
            )
    require_file_write_access(membership)
    return await _confirm_upload(
        db, request=request, actor=actor, workspace=workspace, payload=payload
    )


async def _confirm_upload(
    db: AsyncSession,
    *,
    request: Request,
    actor: User,
    workspace: Workspace | None,
    payload: FileConfirmRequest,
) -> FileRead:
    scope = ContentScope.PLATFORM if workspace is None else ContentScope.WORKSPACE
    workspace_id = workspace.id if workspace is not None else None
    bucket = file_storage_bucket(scope)
    token_payload = verify_asset_upload_token(
        payload.upload_token,
        expected_kind=AssetKind.PLATFORM_FILE if workspace is None else AssetKind.WORKSPACE_FILE,
        actor_user_id=actor.id,
        workspace_id=workspace_id,
    )
    ref = token_ref(token_payload)
    if ref.bucket != bucket or token_payload.workspace_id != workspace_id:
        raise AppValidationError("Upload token is not valid for this file", field="upload_token")
    file_upload = await db.scalar(
        select(FileUpload)
        .where(
            FileUpload.object_key == ref.key,
            FileUpload.workspace_id == workspace_id,
            FileUpload.scope == scope,
            FileUpload.created_by_user_id == actor.id,
        )
        .with_for_update()
    )
    if file_upload is None or str(file_upload.id) != token_payload.jti:
        raise AppValidationError("Upload token is not valid for this file", field="upload_token")
    if file_upload.consumed_at is not None:
        file = await get_file_for_upload(
            db,
            scope=scope,
            workspace_id=workspace_id,
            file_id=file_upload.file_id,
        )
        await best_effort_delete_file_object(ref.key, bucket=bucket)
        return file_to_read(
            file,
            folder_name=await get_file_folder_name(db, workspace=workspace, file=file)
            if workspace
            else None,
            actor=actor,
        )
    if file_upload.expires_at < datetime.now(UTC):
        raise AppValidationError("File upload has expired", field="upload_token")

    uploaded_extension = PurePosixPath(file_upload.filename).suffix.lower()
    if not uploaded_extension:
        raise AppValidationError("Uploaded file has no extension", field="upload_token")
    final_ref = make_storage_object_ref(
        bucket,
        f"{file_storage_prefix(scope, workspace_id)}/files/"
        f"{file_upload.file_id}/{file_upload.revision_id}{uploaded_extension}",
    )

    existing_file = await db.scalar(
        select(File)
        .where(
            File.id == file_upload.file_id,
            File.workspace_id == workspace_id,
            File.scope == scope,
        )
        .with_for_update()
    )
    is_new_file = existing_file is None
    if existing_file is not None and existing_file.deleted:
        raise ConflictError(
            "File was deleted while the upload was in progress",
            conflicting_resource="file",
            details={"file_id": str(existing_file.id)},
        )
    if workspace is not None and is_new_file and payload.folder_id is not None:
        await get_folder_for_workspace(
            db,
            workspace=workspace,
            folder_id=payload.folder_id,
            for_update=True,
        )

    if token_payload.content_type != file_upload.content_type:
        raise AppValidationError(
            "Upload token does not match the declared content type", field="upload_token"
        )
    provider = get_storage_provider()
    allowed_types = {entry.content_type for entry in FILE_CONTRACT}
    source_stored = await provider.stat_object(ref)
    if source_stored is None:
        stored = validate_stored_object(
            await provider.stat_object(final_ref),
            expected_content_type=token_payload.content_type,
            allowed_content_types=allowed_types,
            max_size_bytes=token_payload.max_size_bytes,
            asset_label="file",
        )
        require_declared_upload_size(stored.size_bytes, file_upload)
        content_hash = await sha256_hex_stream(provider.stream_object(final_ref))
    else:
        source_stored = validate_stored_object(
            source_stored,
            expected_content_type=token_payload.content_type,
            allowed_content_types=allowed_types,
            max_size_bytes=token_payload.max_size_bytes,
            asset_label="file",
        )
        require_declared_upload_size(source_stored.size_bytes, file_upload)
        content_hash = await sha256_hex_stream(provider.stream_object(ref))
        if existing_file is not None and existing_file.content_hash == content_hash:
            file_upload.consumed_at = datetime.now(UTC)
            await best_effort_delete_file_object(ref.key, provider=provider, bucket=bucket)
            await db.flush()
            return file_to_read(
                existing_file,
                folder_name=await get_file_folder_name(
                    db,
                    workspace=workspace,
                    file=existing_file,
                )
                if workspace
                else None,
                actor=actor,
            )

        stored, promoted = await promote_object_or_get_existing(
            provider,
            ref,
            final_ref,
            source_object=source_stored,
        )
        stored = validate_stored_object(
            stored,
            expected_content_type=token_payload.content_type,
            allowed_content_types=allowed_types,
            max_size_bytes=token_payload.max_size_bytes,
            asset_label="file",
        )
        require_declared_upload_size(stored.size_bytes, file_upload)
        if not promoted:
            final_hash = await sha256_hex_stream(provider.stream_object(final_ref))
            if final_hash != content_hash:
                raise ConflictError(
                    "Confirmed file bytes do not match the pending upload",
                    conflicting_resource="file_revision",
                    details={"revision_id": str(file_upload.revision_id)},
                )

    entry = require_matching_pair(
        stored.content_type or token_payload.content_type,
        uploaded_extension,
    )

    if is_new_file:
        file = File(
            id=file_upload.file_id,
            workspace_id=workspace_id,
            scope=scope,
            name=file_upload.filename,
            folder_id=payload.folder_id,
            category=entry.category.value,
            content_type=entry.content_type,
            extension=uploaded_extension,
            size_bytes=stored.size_bytes,
            content_hash=content_hash,
            revision_count=0,
            processing_status="ready",
            processing_attempts=0,
        )
        db.add(file)
        await db.flush()
    else:
        file = existing_file
        if file.category != entry.category.value:
            raise AppValidationError(
                "Replacement file must stay in the same category",
                field="content_type",
            )

    revision_kind = "create" if is_new_file else "replace"
    revision = FileRevision(
        id=file_upload.revision_id,
        file_id=file.id,
        workspace_id=workspace_id,
        scope=scope,
        revision_number=file.revision_count + 1,
        revision_kind=revision_kind,
        content_type=entry.content_type,
        extension=uploaded_extension,
        size_bytes=stored.size_bytes,
        content_hash=content_hash,
        object_key=final_ref.key,
        created_by_user_id=actor.id,
    )
    db.add(revision)
    await db.flush()

    file.current_revision_id = revision.id
    if file.scope == ContentScope.PLATFORM and not file.is_published:
        # A fresh draft can process after withdrawal cancelled the previous revision.
        file.published_revision_id = None
    file.revision_count = revision.revision_number
    file.category = entry.category.value
    file.content_type = revision.content_type
    file.extension = revision.extension
    file.size_bytes = revision.size_bytes
    file.content_hash = revision.content_hash
    await set_processing_state_for_revision(
        db,
        file=file,
        revision=revision,
        initiated_by_user_id=actor.id,
    )
    file_upload.consumed_at = datetime.now(UTC)
    await db.flush()
    await best_effort_delete_file_object(ref.key, provider=provider, bucket=bucket)

    if workspace is None:
        await record_platform_content_audit_event(
            db,
            request=request,
            actor=actor,
            resource_type=AuditResourceType.FILE,
            resource_id=file.id,
            details=PlatformContentAuditDetails(
                operation="create" if is_new_file else "replace",
                revision_id=revision.id,
            ),
        )
    else:
        await record_workspace_audit_event(
            db,
            request=request,
            workspace_id=workspace_id,
            action=AuditAction.CREATE,
            resource_type=AuditResourceType.FILE,
            resource_id=file.id,
            actor=actor,
            details={
                "filename": file.name,
                "size_bytes": revision.size_bytes,
                "revision_kind": revision.revision_kind,
                "content_hash": revision.content_hash,
            },
        )
    await db.refresh(file)
    return file_to_read(
        file,
        folder_name=await get_file_folder_name(db, workspace=workspace, file=file)
        if workspace
        else None,
        actor=actor,
    )
