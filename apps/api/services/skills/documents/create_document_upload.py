# apps/api/services/skills/documents/create_document_upload.py

"""Create a direct-upload grant for a skill document."""

from datetime import timedelta
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from core.settings import settings
from models.user import User
from models.workspace import Workspace, WorkspaceMembership
from services.assets.domain import AssetKind, AssetUploadGrant
from services.assets.tokens import create_asset_upload_token
from services.skills.documents.domain import SkillDocumentUploadRequest
from services.skills.documents.utils import original_ref, validate_document_upload
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
    ref = original_ref(
        workspace.id,
        skill.id,
        payload.document_name,
        filename=payload.filename,
    )
    provider = get_storage_provider()
    upload = await provider.create_signed_upload(
        ref,
        content_type=content_type,
        expires_in=timedelta(minutes=10),
    )
    upload_token, expires_at = create_asset_upload_token(
        kind=AssetKind.SKILL_DOCUMENT,
        actor_user_id=actor.id,
        workspace_id=workspace.id,
        ref=ref,
        content_type=content_type,
        max_size_bytes=settings.MAX_FILE_SIZE_DOCUMENT,
    )
    return AssetUploadGrant(
        upload=upload,
        upload_token=upload_token,
        max_size_bytes=settings.MAX_FILE_SIZE_DOCUMENT,
        expires_at=expires_at,
    )
