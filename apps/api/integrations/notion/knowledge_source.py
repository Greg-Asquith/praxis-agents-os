# apps/api/integrations/notion/knowledge_source.py


"""Notion Knowledge Base source adapter."""

import re
from collections.abc import Mapping
from datetime import datetime
from typing import Any
from urllib.parse import urlparse
from uuid import UUID

from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from core.exceptions.integration import (
    IntegrationAuthError,
    IntegrationNotFoundError,
    IntegrationPermissionError,
    IntegrationValidationError,
)
from core.settings import settings
from models.integrations import IntegrationConnection, IntegrationResource
from services.agents.runtime.untrusted import untrusted_content_text
from services.integrations.connections.utils import refresh_oauth_credential
from services.integrations.credentials import ensure_fresh_credential
from services.integrations.domain import CONNECTION_STATUSES_WITHOUT_USABLE_CREDENTIALS
from services.integrations.plugin import (
    IntegrationKnowledgeSourceDefinition,
    KnowledgeSourceAccessLostError,
    KnowledgeSourceDocument,
    KnowledgeSourcePreview,
    KnowledgeSourceSearchResult,
)

from .client import NotionClient
from .operations.get_page import get_page
from .operations.get_page_markdown import get_page_markdown
from .operations.search import search
from .references import NotionPageReference, notion_page_reference

NOTION_KNOWLEDGE_RESOURCE_TYPES = frozenset({"notion_workspace"})
MAX_PREVIEW_MARKDOWN_BYTES = 8 * 1024
_PAGE_ID_SUFFIX = re.compile(r"([0-9a-fA-F]{32})$")


def parse_source(value: str | dict[str, Any]) -> dict[str, Any]:
    """Normalizes a scoped Notion page reference or supported page URL."""
    if isinstance(value, str):
        page_id = _page_id_from_url(value)
        return {"page_id": page_id}
    if not isinstance(value, Mapping):
        raise _source_validation_error()
    if set(value) == {"page_id"}:
        return {"page_id": _normalized_page_id(str(value["page_id"]))}
    try:
        reference = NotionPageReference.model_validate(value)
        page_id = _normalized_page_id(reference.page_id)
    except (ValidationError, ValueError) as exc:
        raise _source_validation_error(original_error=exc) from exc
    return {**reference.model_dump(mode="json"), "page_id": page_id}


async def search_sources(
    db: AsyncSession,
    connection: IntegrationConnection,
    resource: IntegrationResource,
    query: str | None,
    limit: int,
) -> tuple[KnowledgeSourceSearchResult, ...]:
    """Returns bounded Notion page title matches for one connection resource."""
    client = notion_client_for_connection(db, connection)
    result = await search(
        client,
        query=query.strip() if query and query.strip() else None,
        kind="page",
        limit=min(max(limit, 1), 50),
    )
    items: list[KnowledgeSourceSearchResult] = []
    for item in result["items"]:
        reference = notion_page_reference(resource, item)
        if reference is None:
            continue
        page_id = _normalized_provider_page_id(
            reference.page_id,
            operation="search_knowledge_sources",
        )
        items.append(
            KnowledgeSourceSearchResult(
                reference={
                    **reference.model_dump(mode="json"),
                    "page_id": page_id,
                },
                title=untrusted_content_text(item["title"])[:500] or "(untitled)",
                url=_validated_page_url(
                    item["url"],
                    expected_page_id=page_id,
                    operation="search_knowledge_sources",
                ),
                source_updated_at=_source_updated_at(item["last_edited_time"]),
            )
        )
    return tuple(items)


async def preview_source(
    db: AsyncSession,
    connection: IntegrationConnection,
    resource: IntegrationResource,
    reference: dict[str, Any],
) -> KnowledgeSourcePreview:
    """Returns a bounded preview for one Notion page."""
    normalized = _reference_for_resource(reference, resource)
    client = notion_client_for_connection(db, connection)
    metadata, markdown = await _read_page(
        client,
        page_id=normalized.page_id,
        max_bytes=MAX_PREVIEW_MARKDOWN_BYTES,
    )
    canonical_reference = notion_page_reference(resource, metadata)
    if canonical_reference is None:
        raise _invalid_provider_response("preview_source")
    return KnowledgeSourcePreview(
        reference={
            **canonical_reference.model_dump(mode="json"),
            "page_id": _normalized_page_id(canonical_reference.page_id),
        },
        external_id=_normalized_page_id(canonical_reference.page_id),
        title=untrusted_content_text(metadata["title"])[:500] or "(untitled)",
        url=_validated_page_url(
            metadata["url"],
            expected_page_id=normalized.page_id,
            operation="preview_knowledge_source",
        ),
        source_updated_at=_source_updated_at(metadata["last_edited_time"]),
        markdown_excerpt=untrusted_content_text(markdown["markdown"]),
    )


async def fetch_source(
    db: AsyncSession,
    connection: IntegrationConnection,
    resource: IntegrationResource,
    external_id: str,
) -> KnowledgeSourceDocument:
    """Returns one complete Notion page for Knowledge Base ingestion."""
    normalized_id = _normalized_page_id(external_id)
    client = notion_client_for_connection(db, connection)
    metadata, markdown = await _read_page(
        client,
        page_id=normalized_id,
        max_bytes=settings.KB_MAX_DOCUMENT_BYTES,
    )
    if markdown["truncated"]:
        raise IntegrationValidationError(
            "Notion page Markdown exceeds the Knowledge Base document limit",
            provider_key="notion",
            operation="fetch_knowledge_source",
        )
    if markdown["provider_truncated"]:
        raise IntegrationValidationError(
            "Notion returned incomplete page Markdown",
            provider_key="notion",
            operation="fetch_knowledge_source",
        )
    return KnowledgeSourceDocument(
        external_id=_normalized_provider_page_id(
            metadata["id"],
            operation="fetch_knowledge_source",
        ),
        title=untrusted_content_text(metadata["title"])[:500] or "(untitled)",
        url=_validated_page_url(
            metadata["url"],
            expected_page_id=normalized_id,
            operation="fetch_knowledge_source",
        ),
        source_updated_at=_source_updated_at(metadata["last_edited_time"]),
        markdown=untrusted_content_text(markdown["markdown"]),
    )


def notion_client_for_connection(
    db: AsyncSession,
    connection: IntegrationConnection,
) -> NotionClient:
    """Creates a paced Notion client from a visible personal connection."""
    if (
        connection.provider_key != "notion"
        or connection.deleted
        or connection.owner_user_id is None
        or connection.owner_workspace_id is not None
        or connection.status in CONNECTION_STATUSES_WITHOUT_USABLE_CREDENTIALS
    ):
        raise _credential_error(connection)
    if db.in_transaction():
        raise RuntimeError(
            "Notion Knowledge Base source callers must close database transactions "
            "before provider I/O"
        )

    async def access_token(force: bool) -> str:
        try:
            fresh = await ensure_fresh_credential(
                db,
                credential_id=connection.credential_id,
                refresh_token=refresh_oauth_credential,
                force=force,
                expected_provider_key=connection.provider_key,
                expected_owner=(connection.owner_user_id, connection.owner_workspace_id),
            )
        except IntegrationNotFoundError as exc:
            raise _credential_error(connection) from exc
        if (
            fresh.provider_key != connection.provider_key
            or fresh.owner_user_id != connection.owner_user_id
            or fresh.owner_workspace_id != connection.owner_workspace_id
        ):
            raise _credential_error(connection)
        token = fresh.access_token
        if not token:
            raise _credential_error(connection)
        return token

    return NotionClient(access_token, pacing_key=str(connection.id))


async def _read_page(
    client: NotionClient,
    *,
    page_id: str,
    max_bytes: int,
) -> tuple[dict[str, Any], dict[str, Any]]:
    try:
        metadata = await get_page(client, page_id=page_id)
        if _normalized_provider_page_id(
            metadata["id"],
            operation="read_knowledge_source",
        ) != _normalized_page_id(page_id):
            raise _invalid_provider_response("read_knowledge_source")
        markdown = await get_page_markdown(client, page_id=page_id, max_bytes=max_bytes)
    except (IntegrationPermissionError, IntegrationNotFoundError) as exc:
        raise KnowledgeSourceAccessLostError(
            "The Notion page is no longer accessible",
            provider_key="notion",
            operation="read_knowledge_source",
            original_error=exc,
            failure_disposition=exc.failure_disposition,
        ) from exc
    return metadata, markdown


def _reference_for_resource(
    reference: dict[str, Any],
    resource: IntegrationResource,
) -> NotionPageReference:
    parsed = parse_source(reference)
    workspace_id = parsed.get("workspace_id")
    if workspace_id is not None and workspace_id != resource.external_id:
        raise _source_validation_error()
    try:
        return NotionPageReference(
            workspace_id=resource.external_id,
            page_id=parsed["page_id"],
            label=str(parsed.get("label") or "(untitled)")[:500],
            description="Notion page",
            scope_label=resource.display_name,
        )
    except (ValidationError, ValueError) as exc:
        raise _source_validation_error(original_error=exc) from exc


def _page_id_from_url(value: str) -> str:
    parsed = urlparse(value.strip())
    hostname = (parsed.hostname or "").lower().rstrip(".")
    allowed_host = hostname in {"app.notion.com", "notion.so", "www.notion.so"} or (
        hostname.endswith(".notion.site") and hostname != "notion.site"
    )
    segment = parsed.path.rstrip("/").rsplit("/", 1)[-1]
    match = _PAGE_ID_SUFFIX.search(segment)
    if parsed.scheme != "https" or not allowed_host or match is None:
        raise _source_validation_error()
    return _normalized_page_id(match.group(1))


def _normalized_page_id(value: str) -> str:
    try:
        return str(UUID(value.strip()))
    except (AttributeError, ValueError) as exc:
        raise _source_validation_error(original_error=exc) from exc


def _normalized_provider_page_id(value: object, *, operation: str) -> str:
    if not isinstance(value, str):
        raise _invalid_provider_response(operation)
    try:
        return str(UUID(value.strip()))
    except ValueError as exc:
        raise _invalid_provider_response(operation, original_error=exc) from exc


def _validated_page_url(
    value: object,
    *,
    expected_page_id: str,
    operation: str,
) -> str:
    if not isinstance(value, str) or not value:
        raise _invalid_provider_response(operation)
    try:
        parsed_id = _page_id_from_url(value)
    except IntegrationValidationError as exc:
        raise _invalid_provider_response(operation, original_error=exc) from exc
    if parsed_id != _normalized_page_id(expected_page_id):
        raise _invalid_provider_response(operation)
    return value[:2_000]


def _source_updated_at(value: object) -> datetime | None:
    if value is None or value == "":
        return None
    if not isinstance(value, str):
        raise _invalid_provider_response("read_knowledge_source")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise _invalid_provider_response("read_knowledge_source", original_error=exc) from exc
    if parsed.tzinfo is None:
        raise _invalid_provider_response("read_knowledge_source")
    return parsed


def _source_validation_error(
    *, original_error: Exception | None = None
) -> IntegrationValidationError:
    return IntegrationValidationError(
        "Enter a valid Notion page URL or page reference",
        provider_key="notion",
        operation="parse_knowledge_source",
        original_error=original_error,
    )


def _invalid_provider_response(
    operation: str,
    *,
    original_error: Exception | None = None,
) -> IntegrationValidationError:
    return IntegrationValidationError(
        "Notion returned an invalid page response",
        provider_key="notion",
        operation=operation,
        original_error=original_error,
    )


def _credential_error(connection: IntegrationConnection) -> IntegrationAuthError:
    return IntegrationAuthError(
        "Notion connection credentials are not available",
        provider_key="notion",
        connection_id=str(connection.id),
        operation="notion_client_for_connection",
    )


KNOWLEDGE_SOURCE = IntegrationKnowledgeSourceDefinition(
    resource_types=NOTION_KNOWLEDGE_RESOURCE_TYPES,
    parse_source=parse_source,
    search=search_sources,
    preview=preview_source,
    fetch=fetch_source,
)
