# apps/api/services/assets/utils.py

"""Shared helpers for asset upload validation and cleanup."""

import logging
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from fastapi import Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.exceptions.general import AppValidationError, ConflictError
from core.settings import settings
from models.asset_upload import AssetUpload
from models.user import User
from services.assets.domain import (
    AssetConfirmRequest,
    AssetKind,
    AssetSpec,
    AssetUploadGrant,
    AssetUploadRequest,
)
from services.assets.tokens import create_asset_upload_token, token_ref, verify_asset_upload_token
from services.audit_events import AuditAction, AuditResourceType, record_user_audit_event
from services.audit_events.workspace_events import record_workspace_audit_event
from services.auth.schemas import AuthUser
from services.auth.utils import build_auth_user
from services.storage.domain import StorageBucket, StorageObjectRef, StoredObject
from services.storage.factory import get_storage_provider
from services.storage.paths import unique_object_key
from services.storage.provider import StorageProvider
from services.storage.utils import promote_object_or_get_existing
from services.workspaces.schemas import WorkspaceRead
from utils.digests import sha256_hex_stream

logger = logging.getLogger(__name__)

RASTER_ICON_CONTENT_TYPES = frozenset({"image/jpeg", "image/png", "image/webp"})
_IMAGE_EXTENSIONS = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
}


@dataclass(frozen=True)
class AssetMutation:
    """Result of mutating one managed public asset."""

    provider: StorageProvider
    object_key: str | None
    previous_object_key: str | None
    changed: bool = True


def parse_content_types(value: str) -> set[str]:
    """Parse a comma-separated content-type setting."""
    return {item.strip().lower() for item in value.split(",") if item.strip()}


def normalize_content_type(content_type: str) -> str:
    """Return a canonical content type, rejecting header parameters."""
    normalized = content_type.strip().lower()
    if not normalized or ";" in normalized:
        raise AppValidationError("Unsupported file type", field="content_type")
    return normalized


def allowed_avatar_content_types() -> set[str]:
    """Return content types allowed for user-uploaded avatars."""
    return parse_content_types(settings.ALLOWED_IMAGE_TYPES)


def allowed_workspace_icon_content_types() -> set[str]:
    """Return raster content types allowed for workspace icons."""
    return parse_content_types(settings.ALLOWED_ICON_TYPES) & set(RASTER_ICON_CONTENT_TYPES)


USER_AVATAR_ASSET_SPEC = AssetSpec(
    kind=AssetKind.USER_AVATAR,
    asset_label="avatar",
    max_size_setting="MAX_FILE_SIZE_AVATAR",
    allowed_content_types=allowed_avatar_content_types,
    ref_template="users/{owner_id}/avatar",
    url_attr="avatar_url",
    object_key_attr="avatar_object_key",
    audit_fields=("avatar_url", "avatar_object_key"),
)
WORKSPACE_ICON_ASSET_SPEC = AssetSpec(
    kind=AssetKind.WORKSPACE_ICON,
    asset_label="workspace icon",
    max_size_setting="MAX_FILE_SIZE_ICON",
    allowed_content_types=allowed_workspace_icon_content_types,
    ref_template="workspaces/{owner_id}/icon",
    url_attr="icon_url",
    object_key_attr="icon_object_key",
    audit_fields=("icon_url", "icon_object_key"),
)


def asset_audit_details(spec: AssetSpec, mutation: AssetMutation) -> dict[str, Any]:
    """Build the stable audit detail payload for managed asset mutations."""
    return {
        "fields": list(spec.audit_fields),
        "storage_provider": mutation.provider.provider_key,
    }


async def create_asset_upload(
    db: AsyncSession,
    spec: AssetSpec,
    *,
    actor: User,
    owner_id: UUID,
    payload: AssetUploadRequest,
    target_user_id: UUID | None = None,
    workspace_id: UUID | None = None,
) -> AssetUploadGrant:
    """Create a direct-upload grant for one managed public asset."""
    max_size_bytes = int(getattr(settings, spec.max_size_setting))
    content_type = validate_upload_metadata(
        filename=payload.filename,
        content_type=payload.content_type,
        size_bytes=payload.size_bytes,
        allowed_content_types=spec.allowed_content_types(),
        max_size_bytes=max_size_bytes,
        asset_label=spec.asset_label,
    )
    ref = public_asset_upload_ref(
        spec.ref_template.format(owner_id=owner_id),
        content_type=content_type,
    )
    provider = get_storage_provider()
    upload = await provider.create_signed_upload(
        ref,
        content_type=content_type,
        expires_in=timedelta(minutes=10),
    )
    upload_token, expires_at = create_asset_upload_token(
        kind=spec.kind,
        actor_user_id=actor.id,
        target_user_id=target_user_id,
        workspace_id=workspace_id,
        ref=ref,
        content_type=content_type,
        max_size_bytes=max_size_bytes,
        token_id=(token_id := secrets.token_urlsafe(24)),
    )
    db.add(
        AssetUpload(
            token_id=token_id,
            kind=spec.kind.value,
            object_key=ref.key,
            created_by_user_id=actor.id,
            target_user_id=target_user_id,
            workspace_id=workspace_id,
            expires_at=expires_at,
        )
    )
    await db.flush()
    return AssetUploadGrant(
        upload=upload,
        upload_token=upload_token,
        max_size_bytes=max_size_bytes,
        expires_at=expires_at,
    )


async def confirm_asset_upload(
    db: AsyncSession,
    spec: AssetSpec,
    *,
    actor: User,
    target: Any,
    payload: AssetConfirmRequest,
    target_user_id: UUID | None = None,
    workspace_id: UUID | None = None,
) -> AssetMutation:
    """Confirm an uploaded public asset and attach it to the target object."""
    token_payload = verify_asset_upload_token(
        payload.upload_token,
        expected_kind=spec.kind,
        actor_user_id=actor.id,
        target_user_id=target_user_id,
        workspace_id=workspace_id,
    )
    ref = token_ref(token_payload)
    if ref.bucket != StorageBucket.PUBLIC:
        raise AppValidationError(
            f"Upload token is not valid for this {spec.asset_label}",
            field="upload_token",
        )
    upload_record = await db.scalar(
        select(AssetUpload)
        .where(
            AssetUpload.token_id == token_payload.jti,
            AssetUpload.kind == spec.kind.value,
            AssetUpload.object_key == ref.key,
            AssetUpload.created_by_user_id == actor.id,
            (
                AssetUpload.target_user_id == target_user_id
                if target_user_id is not None
                else AssetUpload.target_user_id.is_(None)
            ),
            (
                AssetUpload.workspace_id == workspace_id
                if workspace_id is not None
                else AssetUpload.workspace_id.is_(None)
            ),
        )
        .with_for_update()
    )
    if upload_record is None:
        raise AppValidationError(
            f"Upload token is not valid for this {spec.asset_label}",
            field="upload_token",
        )
    final_ref = public_asset_ref_for_upload(ref)
    provider = get_storage_provider()
    previous_object_key = getattr(target, spec.object_key_attr)
    if upload_record.consumed_at is not None:
        if previous_object_key != final_ref.key:
            raise ConflictError(
                f"This {spec.asset_label} upload has already been replaced",
                conflicting_resource=spec.kind.value,
            )
        stored = validate_stored_object(
            await provider.stat_object(final_ref),
            expected_content_type=token_payload.content_type,
            allowed_content_types=spec.allowed_content_types(),
            max_size_bytes=token_payload.max_size_bytes,
            asset_label=spec.asset_label,
        )
        resolve_public_url(stored, provider=provider, asset_label=spec.asset_label)
        await best_effort_delete_public_object(ref.key, provider=provider)
        return AssetMutation(
            provider=provider,
            object_key=final_ref.key,
            previous_object_key=previous_object_key,
            changed=False,
        )
    if upload_record.expires_at < datetime.now(UTC):
        raise AppValidationError(
            f"{spec.asset_label.capitalize()} upload has expired",
            field="upload_token",
        )

    source_stored = await provider.stat_object(ref)
    if source_stored is None:
        stored = validate_stored_object(
            await provider.stat_object(final_ref),
            expected_content_type=token_payload.content_type,
            allowed_content_types=spec.allowed_content_types(),
            max_size_bytes=token_payload.max_size_bytes,
            asset_label=spec.asset_label,
        )
    else:
        source_stored = validate_stored_object(
            source_stored,
            expected_content_type=token_payload.content_type,
            allowed_content_types=spec.allowed_content_types(),
            max_size_bytes=token_payload.max_size_bytes,
            asset_label=spec.asset_label,
        )
        source_hash = await sha256_hex_stream(provider.stream_object(ref))
        stored, promoted = await promote_object_or_get_existing(
            provider,
            ref,
            final_ref,
            source_object=source_stored,
        )
        stored = validate_stored_object(
            stored,
            expected_content_type=token_payload.content_type,
            allowed_content_types=spec.allowed_content_types(),
            max_size_bytes=token_payload.max_size_bytes,
            asset_label=spec.asset_label,
        )
        if not promoted:
            final_hash = await sha256_hex_stream(provider.stream_object(final_ref))
            if final_hash != source_hash:
                raise ConflictError(
                    f"Confirmed {spec.asset_label} bytes do not match the pending upload",
                    conflicting_resource=spec.kind.value,
                )

    public_url = resolve_public_url(stored, provider=provider, asset_label=spec.asset_label)

    setattr(target, spec.object_key_attr, final_ref.key)
    setattr(target, spec.url_attr, public_url)
    upload_record.consumed_at = datetime.now(UTC)
    await db.flush()
    await best_effort_delete_public_object(ref.key, provider=provider)
    return AssetMutation(
        provider=provider,
        object_key=final_ref.key,
        previous_object_key=previous_object_key,
    )


async def delete_asset(db: AsyncSession, spec: AssetSpec, *, target: Any) -> AssetMutation:
    """Clear one managed public asset from the target object."""
    previous_object_key = getattr(target, spec.object_key_attr)
    provider = get_storage_provider()
    changed = getattr(target, spec.url_attr) is not None or previous_object_key is not None
    if changed:
        setattr(target, spec.url_attr, None)
        setattr(target, spec.object_key_attr, None)
        await db.flush()
    return AssetMutation(
        provider=provider,
        object_key=None,
        previous_object_key=previous_object_key,
        changed=changed,
    )


async def delete_previous_asset_object(mutation: AssetMutation) -> None:
    """Delete a replaced public object after the database mutation is durable."""
    if mutation.previous_object_key and mutation.previous_object_key != mutation.object_key:
        await best_effort_delete_public_object(
            mutation.previous_object_key,
            provider=mutation.provider,
        )


async def confirm_user_asset(
    db: AsyncSession,
    spec: AssetSpec,
    *,
    request: Request,
    actor: User,
    payload: AssetConfirmRequest,
) -> AuthUser:
    """Confirm and audit a managed asset owned by the current user."""
    mutation = await confirm_asset_upload(
        db,
        spec,
        actor=actor,
        target=actor,
        payload=payload,
        target_user_id=actor.id,
    )
    if mutation.changed:
        await record_user_audit_event(
            db,
            action=AuditAction.UPDATE,
            user=actor,
            actor=actor,
            details=asset_audit_details(spec, mutation),
            request=request,
        )
    await delete_previous_asset_object(mutation)
    return await build_auth_user(db, actor)


async def delete_user_asset(
    db: AsyncSession,
    spec: AssetSpec,
    *,
    request: Request,
    actor: User,
) -> AuthUser:
    """Delete and audit a managed asset owned by the current user."""
    mutation = await delete_asset(db, spec, target=actor)
    if mutation.changed:
        await record_user_audit_event(
            db,
            action=AuditAction.UPDATE,
            user=actor,
            actor=actor,
            details=asset_audit_details(spec, mutation),
            request=request,
        )
    await delete_previous_asset_object(mutation)
    return await build_auth_user(db, actor)


async def confirm_workspace_asset(
    db: AsyncSession,
    spec: AssetSpec,
    *,
    request: Request,
    actor: User,
    workspace: Any,
    current_user_role: str,
    payload: AssetConfirmRequest,
) -> WorkspaceRead:
    """Confirm and audit a managed workspace asset."""
    mutation = await confirm_asset_upload(
        db,
        spec,
        actor=actor,
        target=workspace,
        payload=payload,
        workspace_id=workspace.id,
    )
    if mutation.changed:
        await record_workspace_asset_audit(
            db,
            request=request,
            actor=actor,
            workspace=workspace,
            spec=spec,
            mutation=mutation,
        )
    await db.refresh(workspace)
    await delete_previous_asset_object(mutation)
    return WorkspaceRead.from_workspace(workspace, current_user_role=current_user_role)


async def delete_workspace_asset(
    db: AsyncSession,
    spec: AssetSpec,
    *,
    request: Request,
    actor: User,
    workspace: Any,
    current_user_role: str,
) -> WorkspaceRead:
    """Delete and audit a managed workspace asset."""
    mutation = await delete_asset(db, spec, target=workspace)
    if mutation.changed:
        await record_workspace_asset_audit(
            db,
            request=request,
            actor=actor,
            workspace=workspace,
            spec=spec,
            mutation=mutation,
        )
        await db.refresh(workspace)
    await delete_previous_asset_object(mutation)
    return WorkspaceRead.from_workspace(workspace, current_user_role=current_user_role)


async def record_workspace_asset_audit(
    db: AsyncSession,
    *,
    request: Request,
    actor: User,
    workspace: Any,
    spec: AssetSpec,
    mutation: AssetMutation,
) -> None:
    """Record the standard workspace asset update audit event."""
    await record_workspace_audit_event(
        db,
        request=request,
        workspace_id=workspace.id,
        action=AuditAction.UPDATE,
        resource_type=AuditResourceType.WORKSPACE,
        resource_id=workspace.id,
        actor=actor,
        details=asset_audit_details(spec, mutation),
    )


def validate_upload_metadata(
    *,
    filename: str,
    content_type: str,
    size_bytes: int,
    allowed_content_types: set[str],
    max_size_bytes: int,
    asset_label: str,
) -> str:
    """Validate client-declared file metadata before issuing a signed upload."""
    normalized_content_type = normalize_content_type(content_type)
    if normalized_content_type not in allowed_content_types:
        raise AppValidationError(f"Unsupported {asset_label} file type", field="content_type")
    if size_bytes > max_size_bytes:
        raise AppValidationError(
            f"{asset_label.capitalize()} file is too large", field="size_bytes"
        )
    if extension_for_content_type(normalized_content_type) is None:
        raise AppValidationError(f"Unsupported {asset_label} file type", field="content_type")
    if not filename.strip():
        raise AppValidationError("Filename is required", field="filename")
    return normalized_content_type


def extension_for_content_type(content_type: str) -> str | None:
    """Return a safe extension for a supported image content type."""
    return _IMAGE_EXTENSIONS.get(content_type)


def public_asset_upload_ref(prefix: str, *, content_type: str) -> StorageObjectRef:
    """Create a unique temporary public storage ref for a managed asset upload."""
    extension = extension_for_content_type(content_type)
    if extension is None:
        raise AppValidationError("Unsupported file type", field="content_type")
    return StorageObjectRef(
        bucket=StorageBucket.PUBLIC,
        key=unique_object_key(f"{prefix}/uploads", f"asset{extension}"),
    )


def public_asset_ref_for_upload(upload_ref: StorageObjectRef) -> StorageObjectRef:
    """Derive the immutable managed-asset key for one temporary upload ref."""
    prefix, marker, filename = upload_ref.key.rpartition("/uploads/")
    if not prefix or marker != "/uploads/" or not filename:
        raise AppValidationError("Upload token is not valid for this asset", field="upload_token")
    return StorageObjectRef(bucket=StorageBucket.PUBLIC, key=f"{prefix}/{filename}")


def public_ref_from_key(object_key: str) -> StorageObjectRef:
    """Return a public storage ref for a stored object key."""
    return StorageObjectRef(bucket=StorageBucket.PUBLIC, key=object_key)


def validate_stored_object(
    stored: StoredObject | None,
    *,
    expected_content_type: str,
    allowed_content_types: set[str],
    max_size_bytes: int,
    asset_label: str,
) -> StoredObject:
    """Validate provider metadata after the browser has uploaded bytes."""
    if stored is None:
        raise AppValidationError(f"Uploaded {asset_label} was not found", field="upload_token")

    stored_content_type = normalize_content_type(stored.content_type or "")
    if (
        stored_content_type != expected_content_type
        or stored_content_type not in allowed_content_types
    ):
        raise AppValidationError(
            f"Uploaded {asset_label} has an invalid file type", field="content_type"
        )
    if stored.size_bytes > max_size_bytes:
        raise AppValidationError(f"Uploaded {asset_label} is too large", field="size_bytes")
    return stored


def resolve_public_url(
    stored: StoredObject,
    *,
    provider: StorageProvider,
    asset_label: str,
) -> str:
    """Resolve the provider-owned public URL for a confirmed public asset."""
    public_url = stored.public_url or provider.public_url(stored.ref)
    if not public_url:
        raise AppValidationError(
            f"Uploaded {asset_label} is not available as a public asset",
            field="upload_token",
        )
    return public_url


async def best_effort_delete_public_object(
    object_key: str,
    *,
    provider: StorageProvider | None = None,
) -> None:
    """Delete an old or rejected public object without failing the user operation."""
    try:
        storage_provider = provider or get_storage_provider()
        await storage_provider.delete_object(public_ref_from_key(object_key))
    except Exception:
        logger.warning(
            "Failed to delete public asset object",
            extra={"object_key": object_key},
            exc_info=True,
        )
