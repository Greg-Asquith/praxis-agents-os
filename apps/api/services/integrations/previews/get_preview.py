# apps/api/services/integrations/previews/get_preview.py

"""Resolve, dispatch, sanitize, bound, and audit one integration preview."""

import base64
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from core.exceptions.integration import (
    IntegrationNotFoundError,
    IntegrationValidationError,
)
from core.settings import settings
from models.integrations import IntegrationConnection
from models.user import User
from models.workspace import Workspace
from services.audit_events import (
    AuditAction,
    AuditActorType,
    AuditResourceType,
    AuditStatus,
    safe_record_independent_operation_audit_event,
)
from services.integrations.connections.utils import (
    get_visible_connection,
)
from services.integrations.context.domain import ResolvedContextEntry
from services.integrations.plugin import (
    PROVIDER_PLUGINS,
    IntegrationPreviewDefinition,
    IntegrationPreviewRequest,
)
from services.integrations.previews.sanitize import sanitize_preview_html
from services.integrations.previews.schemas import IntegrationPreviewRead

# Each image type a provider may return, by data URL prefix, with its file signature.
_IMAGE_SIGNATURES = {
    "data:image/jpeg;base64,": b"\xff\xd8\xff",
    "data:image/png;base64,": b"\x89PNG\r\n\x1a\n",
}


async def get_integration_preview(
    db: AsyncSession,
    *,
    connection_id: UUID,
    kind: str,
    ref: str,
    actor: User,
    workspace: Workspace,
    scope: ResolvedContextEntry | None = None,
) -> IntegrationPreviewRead:
    connection = await get_visible_connection(
        db,
        connection_id=connection_id,
        actor=actor,
        workspace=workspace,
    )
    definition = _get_preview_definition(connection, kind=kind)

    try:
        if definition.ref_pattern.fullmatch(ref) is None:
            raise IntegrationValidationError(
                "The preview reference is invalid for this provider",
                provider_key=connection.provider_key,
                operation=definition.operation,
            )
        await db.commit()
        request = IntegrationPreviewRequest(
            ref=ref,
            scope_id=scope.external_id if scope else None,
            actor=actor,
            workspace=workspace,
            scope=scope,
        )
        payload = await definition.fetch(db, connection, request)
        content = payload.content
        if len(content.encode("utf-8")) > settings.INTEGRATION_PREVIEW_MAX_BYTES:
            raise IntegrationValidationError(
                "The content is too large to preview",
                provider_key=connection.provider_key,
                connection_id=str(connection_id),
                operation=definition.operation,
            )
        content_type = payload.content_type
        if content_type == "html":
            content = sanitize_preview_html(content)
        elif content_type == "image":
            _require_image_data_url(content, provider_key=connection.provider_key)
    except Exception as exc:
        await _record_preview_failure_audit(
            connection=connection,
            workspace=workspace,
            actor=actor,
            ref=ref,
            operation=definition.operation,
            error_code=exc.__class__.__name__,
        )
        raise

    # Successful previews stay unaudited: the governed tool call that surfaced the
    # content already produced the durable audit row, and per-render read events
    # would only bury it in noise.
    return IntegrationPreviewRead(
        kind=definition.kind,
        content_type=content_type,
        content=content,
        meta=payload.meta,
    )


def _require_image_data_url(content: str, *, provider_key: str) -> None:
    # Providers re-encode images themselves; anything else could carry markup or scripts.
    for prefix, signature in _IMAGE_SIGNATURES.items():
        if content.startswith(prefix):
            try:
                decoded = base64.b64decode(content.removeprefix(prefix), validate=True)
            except ValueError:
                break
            if decoded.startswith(signature):
                return
            break
    raise IntegrationValidationError(
        "The provider returned an invalid image preview",
        provider_key=provider_key,
        operation="preview_image",
    )


def _get_preview_definition(
    connection: IntegrationConnection,
    *,
    kind: str,
) -> IntegrationPreviewDefinition:
    plugin = PROVIDER_PLUGINS.get(connection.provider_key)
    if plugin is not None:
        for definition in plugin.preview_definitions:
            if definition.kind == kind:
                return definition
    raise IntegrationNotFoundError(
        "This connection does not support the requested preview",
        provider_key=connection.provider_key,
        connection_id=str(connection.id),
        operation=f"preview_{kind}",
    )


async def _record_preview_failure_audit(
    *,
    connection: IntegrationConnection,
    workspace: Workspace,
    actor: User,
    ref: str,
    operation: str,
    error_code: str,
) -> None:
    # Audit rows carry the external ref, never provider content.
    await safe_record_independent_operation_audit_event(
        workspace_id=workspace.id,
        action=AuditAction.READ,
        resource_type=AuditResourceType.INTEGRATION_CONNECTION,
        resource_id=connection.id,
        actor_type=AuditActorType.USER,
        actor_id=actor.id,
        actor_display=actor.email,
        requested_by_user_id=actor.id,
        status=AuditStatus.FAILURE,
        details={
            "provider_key": connection.provider_key,
            "provider_operation": operation,
            "external_ref": ref,
            "error_code": error_code,
        },
        request=None,
    )
