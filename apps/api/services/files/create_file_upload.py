# apps/api/services/files/create_file_upload.py

"""Creates signed upload grants for workspace files and platform drafts."""

import logging
from datetime import UTC, datetime, timedelta
from pathlib import PurePosixPath
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import maintenance_async_db_session
from core.dependencies import require_super_admin_user
from core.exceptions.general import AppValidationError
from core.settings import settings
from models.files import File, FileUpload
from models.user import User
from models.workspace import Workspace, WorkspaceMembership
from services.assets.domain import AssetKind
from services.assets.tokens import create_asset_upload_token
from services.files.contract import max_size_bytes, require_matching_pair
from services.files.domain import FileUploadGrant, FileUploadRequest, FileUploadResult
from services.files.get_files_usage import get_files_usage
from services.files.utils import (
    file_storage_bucket,
    file_storage_prefix,
    file_to_read,
    get_file_folder_name,
    get_file_for_upload,
    require_file_write_access,
)
from services.storage.domain import make_storage_object_ref
from services.storage.factory import get_storage_provider
from services.storage.paths import safe_filename, unique_object_key
from utils.content import ContentScope

logger = logging.getLogger(__name__)


async def create_file_upload(
    db: AsyncSession,
    *,
    actor: User,
    workspace: Workspace,
    membership: WorkspaceMembership,
    payload: FileUploadRequest,
    scope: ContentScope = ContentScope.WORKSPACE,
) -> FileUploadResult:
    """Creates a direct-upload grant, or returns an existing deduplicated file."""
    scope = ContentScope(scope)
    if scope == ContentScope.PLATFORM:
        require_super_admin_user(actor)
        await db.commit()
        async with maintenance_async_db_session() as maintenance_db:
            return await _create_upload(
                maintenance_db, actor=actor, workspace=None, payload=payload
            )
    require_file_write_access(membership)
    return await _create_upload(db, actor=actor, workspace=workspace, payload=payload)


async def _create_upload(
    db: AsyncSession,
    *,
    actor: User,
    workspace: Workspace | None,
    payload: FileUploadRequest,
) -> FileUploadResult:
    scope = ContentScope.PLATFORM if workspace is None else ContentScope.WORKSPACE
    workspace_id = workspace.id if workspace is not None else None

    filename = safe_filename(payload.filename)
    extension = PurePosixPath(filename).suffix.lower()
    if not extension:
        raise AppValidationError("Filename must include a supported extension", field="filename")
    entry = require_matching_pair(payload.content_type, extension)
    size_limit = max_size_bytes(entry)
    if payload.size_bytes > size_limit:
        raise AppValidationError("File is too large", field="size_bytes")

    replace_file: File | None = None
    if payload.file_id is not None:
        replace_file = await get_file_for_upload(
            db,
            scope=scope,
            workspace_id=workspace_id,
            file_id=payload.file_id,
        )
        if replace_file.category != entry.category.value:
            raise AppValidationError(
                "Replacement file must stay in the same category",
                field="content_type",
            )

    if (
        workspace is not None
        and payload.file_id is None
        and payload.content_hash
        and not payload.allow_duplicate_content
    ):
        dedup_file = await _find_file_by_current_hash(
            db,
            workspace=workspace,
            content_hash=payload.content_hash,
        )
        if dedup_file is not None:
            return FileUploadResult(
                deduplicated=True,
                file=file_to_read(
                    dedup_file,
                    folder_name=await get_file_folder_name(
                        db,
                        workspace=workspace,
                        file=dedup_file,
                    ),
                ),
            )

    over_soft_limit = False
    if workspace is not None:
        usage = await get_files_usage(db, workspace=workspace)
        over_soft_limit = (
            usage.used_bytes + payload.size_bytes
            > settings.FILES_WORKSPACE_STORAGE_SOFT_LIMIT_BYTES
        )
        if over_soft_limit:
            logger.warning(
                "Workspace file upload would exceed the soft storage limit",
                extra={
                    "workspace_id": str(workspace.id),
                    "used_bytes": usage.used_bytes,
                    "declared_size_bytes": payload.size_bytes,
                    "soft_limit_bytes": settings.FILES_WORKSPACE_STORAGE_SOFT_LIMIT_BYTES,
                },
            )

    file_id = replace_file.id if replace_file is not None else uuid4()
    revision_id = uuid4()
    object_key = unique_object_key(
        f"{file_storage_prefix(scope, workspace_id)}/uploads/files", f"upload{extension}"
    )
    upload_id = uuid4()
    expires_at = datetime.now(UTC) + timedelta(hours=settings.FILES_UPLOAD_EXPIRY_HOURS)
    db.add(
        FileUpload(
            id=upload_id,
            scope=scope,
            workspace_id=workspace_id,
            file_id=file_id,
            revision_id=revision_id,
            object_key=object_key,
            filename=filename,
            content_type=entry.content_type,
            declared_size_bytes=payload.size_bytes,
            declared_content_hash=payload.content_hash,
            created_by_user_id=actor.id,
            expires_at=expires_at,
        )
    )
    await db.flush()

    ref = make_storage_object_ref(file_storage_bucket(scope), object_key)
    provider = get_storage_provider()
    upload = await provider.create_signed_upload(
        ref,
        content_type=entry.content_type,
        expected_size_bytes=payload.size_bytes,
        expires_in=timedelta(minutes=10),
    )
    upload_token, token_expires_at = create_asset_upload_token(
        kind=AssetKind.PLATFORM_FILE if workspace is None else AssetKind.WORKSPACE_FILE,
        token_id=str(upload_id),
        actor_user_id=actor.id,
        workspace_id=workspace_id,
        ref=ref,
        content_type=entry.content_type,
        max_size_bytes=size_limit,
    )
    return FileUploadResult(
        grant=FileUploadGrant(
            upload=upload,
            upload_token=upload_token,
            max_size_bytes=size_limit,
            expires_at=token_expires_at,
            over_soft_limit=over_soft_limit,
            file_id=file_id,
        )
    )


async def _find_file_by_current_hash(
    db: AsyncSession,
    *,
    workspace: Workspace,
    content_hash: str,
) -> File | None:
    return await db.scalar(
        select(File).where(
            File.workspace_id == workspace.id,
            File.deleted.is_(False),
            File.content_hash == content_hash,
            File.current_revision_id.is_not(None),
        )
    )
