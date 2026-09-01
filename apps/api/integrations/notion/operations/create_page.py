# apps/api/integrations/notion/operations/create_page.py

"""Prepare a bounded Notion page creation against live parent state."""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Literal

from pydantic_ai import ModelRetry

from services.integrations.context.domain import ResolvedContextEntry
from services.integrations.http import IntegrationRequestPolicy

from ..client import NotionClient
from ..references import NotionDataSourceReference, NotionPageReference
from .properties import (
    NotionMutationTarget,
    NotionPropertyRecordLike,
    data_source_title_property,
    encode_property_value,
    get_data_source_mutation_target,
    get_page_mutation_target,
    validate_mutation_scope,
    validate_property_records_against_schema,
    validate_utf8_text,
)
from .utils import normalized_page_mutation_response, validate_mutation_body_size

MAX_NOTION_PAGE_TITLE_CHARS = 500
MAX_NOTION_PAGE_TITLE_BYTES = MAX_NOTION_PAGE_TITLE_CHARS * 4
MAX_NOTION_CREATE_MARKDOWN_BYTES = 256 * 1024


@dataclass(frozen=True)
class CreatePagePreparation:
    """Carries the live parent and encoded properties for page creation."""

    parent: NotionMutationTarget
    parent_type: Literal["page_id", "data_source_id"]
    title: str
    content_md: str
    property_count: int
    properties: dict[str, dict[str, Any]]


async def prepare_create_page(
    client: NotionClient,
    entry: ResolvedContextEntry,
    *,
    parent_page: NotionPageReference | None,
    parent_data_source: NotionDataSourceReference | None,
    title: str,
    content_md: str,
    properties: Sequence[NotionPropertyRecordLike],
) -> CreatePagePreparation:
    """Validates page creation against the live parent and property schema."""
    if (parent_page is None) == (parent_data_source is None):
        raise ModelRetry("Choose one Notion page or data source as the parent.")
    normalized_title = title.strip()
    try:
        validate_utf8_text(
            normalized_title,
            field_name="Page title",
            min_chars=1,
            max_chars=MAX_NOTION_PAGE_TITLE_CHARS,
            max_bytes=MAX_NOTION_PAGE_TITLE_BYTES,
        )
        validate_utf8_text(
            content_md,
            field_name="Page content",
            min_chars=0,
            max_chars=MAX_NOTION_CREATE_MARKDOWN_BYTES,
            max_bytes=MAX_NOTION_CREATE_MARKDOWN_BYTES,
        )
    except ValueError as exc:
        raise ModelRetry(str(exc)) from exc

    if parent_page is not None:
        validate_mutation_scope(entry, parent_page.provider_scope_id, reference_label="parent")
        if properties:
            raise ModelRetry("A page parent accepts a title but no additional properties.")
        parent = await get_page_mutation_target(client, parent_page)
        encoded_properties = {"title": encode_property_value("title", normalized_title)}
        parent_type = "page_id"
    else:
        if parent_data_source is None:
            raise RuntimeError("Notion page preparation requires one parent")
        validate_mutation_scope(
            entry,
            parent_data_source.provider_scope_id,
            reference_label="parent",
        )
        parent = await get_data_source_mutation_target(client, parent_data_source)
        title_property = data_source_title_property(parent)
        encoded_properties = {
            title_property: encode_property_value("title", normalized_title),
            **validate_property_records_against_schema(
                properties,
                parent,
                reserved_property_name=title_property,
            ),
        }
        parent_type = "data_source_id"

    prepared = CreatePagePreparation(
        parent=parent,
        parent_type=parent_type,
        title=normalized_title,
        content_md=content_md,
        property_count=len(properties),
        properties=encoded_properties,
    )
    try:
        validate_mutation_body_size(create_page_request_body(prepared))
    except ValueError as exc:
        raise ModelRetry(str(exc)) from exc
    return prepared


def create_page_request_body(prepared: CreatePagePreparation) -> dict[str, Any]:
    """Builds the exact provider request body for a prepared page creation."""
    payload: dict[str, Any] = {
        "parent": {
            "type": prepared.parent_type,
            prepared.parent_type: prepared.parent.external_id,
        },
        "properties": prepared.properties,
    }
    if prepared.content_md:
        payload["markdown"] = prepared.content_md
    return payload


async def create_page(
    client: NotionClient,
    *,
    prepared: CreatePagePreparation,
) -> dict[str, str]:
    """Creates one page with a synchronous, non-retried provider mutation."""
    payload = await client.post(
        "pages",
        operation="create_page",
        policy=IntegrationRequestPolicy.MUTATION,
        json=create_page_request_body(prepared),
        validation_error_detail=lambda _response: "Notion rejected the page creation request.",
    )
    result = normalized_page_mutation_response(
        payload,
        operation="create_page",
        forbidden_id=prepared.parent.external_id,
        require_new_uuid=True,
    )
    return {**result, "title": prepared.title}
