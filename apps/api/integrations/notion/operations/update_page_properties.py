# apps/api/integrations/notion/operations/update_page_properties.py

"""Prepare a Notion property update against the live page schema."""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from pydantic_ai import ModelRetry

from services.integrations.context.domain import ResolvedContextEntry

from ..client import NotionClient
from ..references import NotionPageReference
from .properties import (
    NotionMutationTarget,
    NotionPropertyRecordLike,
    get_page_mutation_target,
    validate_mutation_scope,
    validate_property_records_against_schema,
)


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
    return UpdatePagePropertiesPreparation(
        page=target,
        records=tuple(properties),
        properties=validate_property_records_against_schema(properties, target),
    )
