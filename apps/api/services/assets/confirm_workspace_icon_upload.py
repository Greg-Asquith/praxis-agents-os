# apps/api/services/assets/confirm_workspace_icon_upload.py

"""Confirm an uploaded workspace icon and attach it to the workspace."""

from uuid import UUID

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

from models.user import User
from services.assets.domain import AssetConfirmRequest, AssetKind
from services.assets.tokens import token_ref, verify_asset_upload_token
from services.assets.utils import (
    allowed_workspace_icon_content_types,
    best_effort_delete_public_object,
    resolve_public_url,
    validate_stored_object,
)
from services.audit_events import AuditAction, AuditResourceType
from services.audit_events.workspace_events import record_workspace_audit_event
from services.storage.factory import get_storage_provider
from services.workspaces.schemas import WorkspaceRead
from services.workspaces.utils import MANAGER_ROLES, require_workspace_role


async def confirm_workspace_icon_upload(
    db: AsyncSession,
    *,
    request: Request,
    actor: User,
    workspace_id: UUID,
    payload: AssetConfirmRequest,
) -> WorkspaceRead:
    workspace, membership = await require_workspace_role(
        db,
        actor=actor,
        workspace_id=workspace_id,
        allowed_roles=MANAGER_ROLES,
    )
    token_payload = verify_asset_upload_token(
        payload.upload_token,
        expected_kind=AssetKind.WORKSPACE_ICON,
        actor_user_id=actor.id,
        workspace_id=workspace_id,
    )
    ref = token_ref(token_payload)
    provider = get_storage_provider()

    try:
        stored = validate_stored_object(
            await provider.stat_object(ref),
            expected_content_type=token_payload.content_type,
            allowed_content_types=allowed_workspace_icon_content_types(),
            max_size_bytes=token_payload.max_size_bytes,
            asset_label="workspace icon",
        )
        public_url = resolve_public_url(stored, provider=provider, asset_label="workspace icon")
    except Exception:
        await best_effort_delete_public_object(ref.key, provider=provider)
        raise

    previous_object_key = workspace.icon_object_key
    workspace.icon_object_key = ref.key
    workspace.icon_url = public_url
    await db.flush()
    await record_workspace_audit_event(
        db,
        request=request,
        workspace_id=workspace.id,
        action=AuditAction.UPDATE,
        resource_type=AuditResourceType.WORKSPACE,
        resource_id=workspace.id,
        actor=actor,
        details={
            "fields": ["icon_url", "icon_object_key"],
            "storage_provider": provider.provider_key,
        },
    )
    await db.refresh(workspace)

    if previous_object_key and previous_object_key != ref.key:
        await best_effort_delete_public_object(previous_object_key, provider=provider)

    return WorkspaceRead.from_workspace(workspace, current_user_role=membership.role)
