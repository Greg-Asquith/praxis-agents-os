# apps/api/integrations/notion/entity_resolvers/data_source.py

"""Notion data-source lookup for shared runtime entity selectors."""

from integrations.notion.operations.get_data_source import get_data_source
from integrations.notion.references import (
    NotionDataSourceReference,
    notion_data_source_reference,
)
from services.integrations.entity_references import EntityChoice, EntityResolverDefinition

from .utils import resolve_entities, search_entities


def _choice(entry, payload) -> EntityChoice | None:
    reference = notion_data_source_reference(entry, payload)
    return EntityChoice.from_reference(reference, icon="notion") if reference else None


async def search_notion_data_sources(ctx, search, _dependent_args, page_size, cursor):
    return await search_entities(
        ctx,
        search,
        kind="data_source",
        page_size=page_size,
        cursor=cursor,
        choice=_choice,
    )


async def resolve_notion_data_sources(ctx, values, _dependent_args):
    async def hydrate(client, reference):
        return await get_data_source(client, data_source_id=reference.data_source_id)

    return await resolve_entities(
        ctx,
        values,
        reference_type=NotionDataSourceReference,
        hydrate=hydrate,
        choice=_choice,
    )


NOTION_DATA_SOURCE_RESOLVER = EntityResolverDefinition(
    entity_kind="notion_data_source",
    reference_type=NotionDataSourceReference,
    search=search_notion_data_sources,
    resolve=resolve_notion_data_sources,
    max_page_size=20,
    requires_active_context=True,
    provider_key="notion",
)
