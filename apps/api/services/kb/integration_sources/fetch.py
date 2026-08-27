# apps/api/services/kb/integration_sources/fetch.py

"""Fetch a bound integration document through its creator's personal grant."""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import (
    configure_async_db_session,
    get_async_db_session_factory,
    set_session_tenant_context,
)
from core.exceptions.integration import IntegrationValidationError
from models.kb import KBDocument
from models.workspace import WorkspaceMembership
from services.integrations.plugin import (
    KnowledgeSourceDisconnectedError,
    KnowledgeSourceDocument,
)
from services.kb.integration_sources.domain import AuthorizedIntegrationKnowledgeSource
from services.kb.integration_sources.utils import load_personal_knowledge_source


async def fetch_integration_source(document: KBDocument) -> KnowledgeSourceDocument:
    """Returns canonical Markdown through the document creator's active grant."""
    workspace_id = document.workspace_id
    creator_id = document.created_by_user_id
    resource_id = document.integration_resource_id
    external_id = document.external_id
    if creator_id is None or resource_id is None or not external_id:
        raise _disconnected()

    session_factory = get_async_db_session_factory()
    async with session_factory() as fetch_db:
        await configure_async_db_session(fetch_db)
        await set_session_tenant_context(
            fetch_db,
            workspace_id=workspace_id,
            user_id=creator_id,
        )
        authorized = await _load_bound_source(
            fetch_db,
            workspace_id=workspace_id,
            creator_id=creator_id,
            resource_id=resource_id,
        )

        await fetch_db.commit()
        source_document = await authorized.definition.fetch(
            fetch_db,
            authorized.connection,
            authorized.resource,
            external_id,
        )
        if source_document.external_id != external_id:
            raise IntegrationValidationError(
                "The integration returned a different source document",
                provider_key=authorized.connection.provider_key,
                operation="fetch_knowledge_source",
            )
        await _load_bound_source(
            fetch_db,
            workspace_id=workspace_id,
            creator_id=creator_id,
            resource_id=resource_id,
        )
        await fetch_db.commit()
        return source_document


async def _load_bound_source(
    db: AsyncSession,
    *,
    workspace_id: UUID,
    creator_id: UUID,
    resource_id: UUID,
) -> AuthorizedIntegrationKnowledgeSource:
    membership_id = await db.scalar(
        select(WorkspaceMembership.id).where(
            WorkspaceMembership.workspace_id == workspace_id,
            WorkspaceMembership.user_id == creator_id,
            WorkspaceMembership.deleted.is_(False),
        )
    )
    if membership_id is None:
        raise _disconnected()

    return await load_personal_knowledge_source(
        db,
        resource_id=resource_id,
        owner_user_id=creator_id,
        unavailable_error=lambda provider_key: _disconnected(provider_key=provider_key),
    )


def _disconnected(*, provider_key: str | None = None) -> KnowledgeSourceDisconnectedError:
    return KnowledgeSourceDisconnectedError(
        "The integration connection for this document is no longer available",
        provider_key=provider_key,
        operation="fetch_knowledge_source",
    )
