# apps/api/integrations/notion/entity_resolvers/page.py

"""Notion page lookup for shared runtime entity selectors."""

from integrations.notion.operations.get_page import get_page
from integrations.notion.references import NotionPageReference, notion_page_reference
from services.integrations.entity_references import EntityChoice, EntityResolverDefinition

from .utils import resolve_entities, search_entities


def _choice(entry, payload) -> EntityChoice | None:
    reference = notion_page_reference(entry, payload)
    return EntityChoice.from_reference(reference, icon="notion") if reference else None


async def search_notion_pages(ctx, search, _dependent_args, page_size, cursor):
    return await search_entities(
        ctx,
        search,
        kind="page",
        page_size=page_size,
        cursor=cursor,
        choice=_choice,
    )


async def resolve_notion_pages(ctx, values, _dependent_args):
    async def hydrate(client, reference):
        return await get_page(client, page_id=reference.page_id)

    return await resolve_entities(
        ctx,
        values,
        reference_type=NotionPageReference,
        hydrate=hydrate,
        choice=_choice,
    )


NOTION_PAGE_RESOLVER = EntityResolverDefinition(
    entity_kind="notion_page",
    reference_type=NotionPageReference,
    search=search_notion_pages,
    resolve=resolve_notion_pages,
    max_page_size=20,
    requires_active_context=True,
    provider_key="notion",
)
