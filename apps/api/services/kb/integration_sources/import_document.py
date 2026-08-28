# apps/api/services/kb/integration_sources/import_document.py

"""Import one integration source into the Knowledge Base."""

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

from core.exceptions.integration import IntegrationAuthError
from models.user import User
from models.workspace import Workspace, WorkspaceMembership
from services.audit_events import AuditAction
from services.kb.create_document import create_kb_document
from services.kb.documents.utils import (
    record_document_audit,
    user_provenance,
)
from services.kb.domain import KB_SOURCE_INTEGRATION
from services.kb.integration_sources.reauthorize import (
    reauthorize_integration_knowledge_source,
)
from services.kb.integration_sources.utils import map_knowledge_source_auth_error
from services.kb.schemas import KBDocumentRead, KBIntegrationDocumentCreateRequest


async def import_integration_document(
    db: AsyncSession,
    *,
    request: Request,
    actor: User,
    workspace: Workspace,
    membership: WorkspaceMembership,
    payload: KBIntegrationDocumentCreateRequest,
) -> KBDocumentRead:
    """Creates a private-by-default document from one actor-owned provider source."""
    authorized = await reauthorize_integration_knowledge_source(
        db,
        integration_resource_id=payload.integration_resource_id,
        membership_id=membership.id,
        actor=actor,
        workspace=workspace,
    )
    normalized_reference = authorized.definition.parse_source(payload.source)

    # Credential refresh and provider reads must not inherit the authorization transaction.
    await db.commit()
    try:
        preview = await authorized.definition.preview(
            db,
            authorized.connection,
            authorized.resource,
            normalized_reference,
        )
    except IntegrationAuthError as exc:
        raise map_knowledge_source_auth_error(exc) from exc
    authorized = await reauthorize_integration_knowledge_source(
        db,
        integration_resource_id=payload.integration_resource_id,
        membership_id=membership.id,
        actor=actor,
        workspace=workspace,
    )
    title = payload.title.strip() if payload.title is not None else preview.title
    provider_key = authorized.connection.provider_key
    document = await create_kb_document(
        db,
        workspace_id=workspace.id,
        source_type=KB_SOURCE_INTEGRATION,
        title=title,
        created_by_user_id=actor.id,
        url=preview.url,
        external_id=preview.external_id,
        integration_resource_id=authorized.resource.id,
        is_private=payload.is_private,
        provenance=user_provenance(
            user_id=actor.id,
            source_type=KB_SOURCE_INTEGRATION,
            origin_ref=preview.url,
        ),
        meta={
            "provider_key": provider_key,
            "source_title": preview.title[:500],
        },
    )
    await record_document_audit(
        db,
        request=request,
        actor=actor,
        document=document,
        action=AuditAction.CREATE,
        details={
            "source_type": document.source_type,
            "is_private": document.is_private,
            "provider_key": provider_key,
        },
    )
    await db.refresh(document)
    return KBDocumentRead.from_document(document)
