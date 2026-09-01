# apps/api/integrations/notion/operations/update_page_properties.py

"""Prepare a Notion property update against the live page schema."""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any
from urllib.parse import quote

from pydantic_ai import ModelRetry

from services.integrations.context.domain import ResolvedContextEntry
from services.integrations.http import IntegrationRequestPolicy

from ..client import NotionClient
from ..references import NotionDataSourceReference, NotionPageReference
from .properties import (
    NotionMutationTarget,
    NotionPropertyRecordLike,
    get_data_source_mutation_target,
    get_page_mutation_target,
    validate_mutation_scope,
    validate_property_records_against_schema,
)
from .utils import normalized_page_mutation_response, validate_mutation_body_size


@dataclass(frozen=True)
class UpdatePagePropertiesPreparation:
    """Carries the live page and schema-validated provider values."""

    page: NotionMutationTarget
    records: tuple[NotionPropertyRecordLike, ...]
    properties: dict[str, dict[str, Any]]


async def prepare_update_page_properties(
    client: NotionClient,
    entry: ResolvedContextEntry,
    *,
    page: NotionPageReference,
    properties: Sequence[NotionPropertyRecordLike],
) -> UpdatePagePropertiesPreparation:
    """Validates property updates against the live target page schema."""
    validate_mutation_scope(entry, page.provider_scope_id, reference_label="page")
    if not properties:
        raise ModelRetry("Add at least one Notion property update.")
    target = await get_page_mutation_target(client, page)
    schema_target = target
    if any(record.type in {"select", "status", "multi_select"} for record in properties):
        if target.parent_data_source_id is None:
            raise ModelRetry(
                "The selected Notion page has no data source schema for these option values."
            )
        schema_target = await get_data_source_mutation_target(
            client,
            NotionDataSourceReference(
                workspace_id=page.workspace_id,
                data_source_id=target.parent_data_source_id,
                label="Parent data source",
                description="Notion data source",
                scope_label=page.scope_label,
            ),
        )
    return UpdatePagePropertiesPreparation(
        page=target,
        records=tuple(properties),
        properties=validate_property_records_against_schema(properties, schema_target),
    )


def update_page_properties_request_body(
    prepared: UpdatePagePropertiesPreparation,
) -> dict[str, Any]:
    """Builds the exact provider request body for prepared property updates."""
    payload = {"properties": prepared.properties}
    validate_mutation_body_size(payload)
    return payload


async def update_page_properties(
    client: NotionClient,
    *,
    prepared: UpdatePagePropertiesPreparation,
) -> dict[str, str]:
    """Updates page properties with a synchronous, non-retried provider mutation."""
    page_id = prepared.page.external_id
    payload = await client.patch(
        f"pages/{quote(page_id, safe='')}",
        operation="update_page_properties",
        policy=IntegrationRequestPolicy.MUTATION,
        json=update_page_properties_request_body(prepared),
        validation_error_detail=lambda _response: (
            "Notion rejected one or more page property values."
        ),
    )
    return normalized_page_mutation_response(
        payload,
        operation="update_page_properties",
        expected_id=page_id,
    )
