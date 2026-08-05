# apps/api/services/skills/documents/create_document_upload.py

"""Create a direct-upload grant for a skill document."""

import secrets
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from core.exceptions.general import AppValidationError
from core.settings import settings
from models.asset_upload import AssetUpload
from models.user import User
from models.workspace import Workspace, WorkspaceMembership
from services.assets.domain import AssetKind, AssetUploadGrant
from services.assets.tokens import create_asset_upload_token
from services.skills.documents.domain import SkillDocumentUploadRequest
from services.skills.documents.utils import upload_ref, validate_document_upload
from services.skills.utils import get_skill_for_workspace, require_skill_write_access
from services.storage.factory import get_storage_provider


async def create_skill_document_upload(
    db: AsyncSession,
    *,
    actor: User,
    workspace: Workspace,
    membership: WorkspaceMembership,
    skill_id: UUID,
    payload: SkillDocumentUploadRequest,
) -> AssetUploadGrant:
    """Create a signed upload grant for a private skill document original."""
    require_skill_write_access(membership)
    skill = await get_skill_for_workspace(db, workspace=workspace, skill_id=skill_id)
    content_type = validate_document_upload(
        payload,
        existing_manifest=skill.documentation_refs,
    )
    lock_material = f"skill-document-upload:{workspace.id}:{actor.id}".encode()
    lock_key = int.from_bytes(sha256(lock_material).digest()[:8], "big", signed=True)
    await db.execute(select(func.pg_advisory_xact_lock(lock_key)))
    pending_upload_count = await db.scalar(
        select(func.count())
        .select_from(AssetUpload)
        .where(
            AssetUpload.kind == AssetKind.SKILL_DOCUMENT.value,
            AssetUpload.created_by_user_id == actor.id,
            AssetUpload.workspace_id == workspace.id,
            AssetUpload.consumed_at.is_(None),
            AssetUpload.expires_at >= datetime.now(UTC),
        )
    )
    if (pending_upload_count or 0) >= settings.MAX_PENDING_SKILL_DOCUMENT_UPLOADS:
        raise AppValidationError(
            "Too many pending skill document uploads",
            field="document_name",
            details={"limit": settings.MAX_PENDING_SKILL_DOCUMENT_UPLOADS},
        )
    ref = upload_ref(
        workspace.id,
        skill.id,
        payload.document_name,
        filename=payload.filename,
    )
    provider = get_storage_provider()
    upload = await provider.create_signed_upload(
        ref,
        content_type=content_type,
        expected_size_bytes=payload.size_bytes,
        expires_in=timedelta(minutes=10),
    )
    upload_token, expires_at = create_asset_upload_token(
        kind=AssetKind.SKILL_DOCUMENT,
        actor_user_id=actor.id,
        workspace_id=workspace.id,
        ref=ref,
        content_type=content_type,
        max_size_bytes=settings.MAX_FILE_SIZE_DOCUMENT,
        token_id=(token_id := secrets.token_urlsafe(24)),
    )
    db.add(
        AssetUpload(
            token_id=token_id,
            kind=AssetKind.SKILL_DOCUMENT.value,
            object_key=ref.key,
            created_by_user_id=actor.id,
            workspace_id=workspace.id,
            expires_at=expires_at,
        )
    )
    await db.flush()
    return AssetUploadGrant(
        upload=upload,
        upload_token=upload_token,
        max_size_bytes=settings.MAX_FILE_SIZE_DOCUMENT,
        expires_at=expires_at,
    )
