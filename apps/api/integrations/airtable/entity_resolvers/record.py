# apps/api/integrations/airtable/entity_resolvers/record.py

"""Airtable record lookup for shared runtime entity selectors."""

import asyncio
from collections import defaultdict
from collections.abc import Mapping, Sequence
from typing import Any

from core.exceptions.integration import IntegrationNotFoundError
from integrations.airtable.operations.get_record import get_record
from integrations.airtable.operations.list_records import list_records
from integrations.airtable.references import (
    AirtableRecordReference,
    airtable_record_reference,
    airtable_tables_match,
)
from integrations.airtable.tools.utils import AIRTABLE_BINDING, airtable_client_for_principal
from services.integrations.entity_references import (
    EntityChoice,
    EntityResolverDefinition,
    EntityResolverPage,
)

MAX_SEARCH_CHOICES = 100


def _offset(cursor: str | None) -> int:
    try:
        return min(max(int(cursor or "0"), 0), MAX_SEARCH_CHOICES)
    except ValueError:
        return 0


def _choice(entry, table: str, record: Mapping[str, Any]) -> EntityChoice | None:
    reference = airtable_record_reference(entry, table, record)
    return EntityChoice.from_reference(reference, icon="airtable") if reference else None


async def search_airtable_records(ctx, search, dependent_args, page_size, cursor):
    table = str(dependent_args.get("table") or "").strip()
    if not table:
        return EntityResolverPage(choices=())
    offset = _offset(cursor)
    request_limit = min(max(offset + page_size + 1, page_size), MAX_SEARCH_CHOICES)
    query = search.strip().casefold()

    async def search_entry(entry) -> list[EntityChoice]:
        client = await airtable_client_for_principal(
            ctx.db,
            actor=ctx.actor,
            workspace=ctx.workspace,
            entry=entry,
        )
        result = await list_records(
            client,
            base_id=entry.external_id,
            table=table,
            max_records=request_limit,
        )
        entry_choices: list[EntityChoice] = []
        for record in result.get("records", []):
            if not isinstance(record, Mapping):
                continue
            choice = _choice(entry, table, record)
            if choice is not None and (
                not query
                or query in choice.label.casefold()
                or query in (choice.description or "").casefold()
            ):
                entry_choices.append(choice)
        return entry_choices

    entries = ctx.active_context.compatible_entries(AIRTABLE_BINDING)
    choices = [
        choice
        for entry_choices in await asyncio.gather(*(search_entry(entry) for entry in entries))
        for choice in entry_choices
    ]
    bounded_choices = choices[:MAX_SEARCH_CHOICES]
    selected = bounded_choices[offset : offset + page_size]
    return EntityResolverPage(
        choices=tuple(selected),
        next_cursor=(
            str(offset + page_size) if len(bounded_choices) > offset + page_size else None
        ),
    )


async def resolve_airtable_records(ctx, values: Sequence[Any], dependent_args):
    table = str(dependent_args.get("table") or "").strip()
    entries = {
        entry.integration_resource_id: entry
        for entry in ctx.active_context.compatible_entries(AIRTABLE_BINDING)
    }
    grouped: dict[Any, list[AirtableRecordReference]] = defaultdict(list)
    for value in values:
        try:
            reference = AirtableRecordReference.model_validate(value)
        except ValueError:
            continue
        if reference.integration_resource_id not in entries:
            continue
        if table and not airtable_tables_match(reference.table, table):
            continue
        grouped[reference.integration_resource_id].append(reference)

    choices: list[EntityChoice] = []
    for resource_id, references in grouped.items():
        entry = entries[resource_id]
        client = await airtable_client_for_principal(
            ctx.db,
            actor=ctx.actor,
            workspace=ctx.workspace,
            entry=entry,
        )
        for reference in references[:25]:
            try:
                record = await get_record(
                    client,
                    base_id=entry.external_id,
                    table=reference.table,
                    record_id=reference.external_id,
                )
            except IntegrationNotFoundError:
                # Records can disappear between selection and exact hydration.
                # An omitted choice makes the stale reference unavailable without
                # turning the rest of the batch into a provider failure.
                continue
            choice = _choice(entry, reference.table, record)
            if choice is not None:
                choices.append(choice)
    return tuple(choices)


AIRTABLE_RECORD_RESOLVER = EntityResolverDefinition(
    entity_kind="airtable_record",
    reference_type=AirtableRecordReference,
    search=search_airtable_records,
    resolve=resolve_airtable_records,
    max_page_size=20,
    requires_active_context=True,
    provider_key="airtable",
)
