# apps/api/integrations/sharepoint/entity_resolvers/drive_item.py

"""Searches and resolves SharePoint item references within selected drives."""

from collections import Counter

from core.exceptions.integration import IntegrationNotFoundError, IntegrationValidationError
from services.integrations.entity_references import (
    EntityResolverDefinition,
    EntityResolverPage,
)

from ..operations.get_item import get_item
from ..operations.list_children import list_children
from ..operations.search_items import search_items as search_drive_items
from ..operations.utils import item_result
from ..references import SharePointDriveItemReference
from ..tools.utils import SHAREPOINT_DRIVE_BINDING, drive_client_for_principal
from .utils import item_choice


async def search_items(ctx, search, _dependent_args, page_size, cursor):
    query = search.strip()[:200]
    try:
        offset = max(0, min(int(cursor or "0"), 25))
    except ValueError:
        offset = 0
    page_size = max(1, min(page_size, 25))
    entries = ctx.active_context.compatible_entries(SHAREPOINT_DRIVE_BINDING)
    drive_counts = Counter(entry.external_id for entry in entries)
    choices = []
    for entry in entries:
        if drive_counts[entry.external_id] != 1:
            continue
        if len(choices) >= 25:
            break
        client = await drive_client_for_principal(
            ctx.db, actor=ctx.actor, workspace=ctx.workspace, entry=entry
        )
        if query:
            result = await search_drive_items(
                client, drive_id=entry.external_id, query=query, limit=25 - len(choices)
            )
        else:
            result = await list_children(
                client, drive_id=entry.external_id, limit=25 - len(choices)
            )
        choices.extend(
            item_choice(entry, item)
            for item in result["items"]
            if query.casefold() in item["name"].content.casefold()
        )
    return EntityResolverPage(
        choices=tuple(choices[offset : offset + page_size]),
        next_cursor=str(offset + page_size) if len(choices) > offset + page_size else None,
    )


async def resolve_items(ctx, values, _dependent_args):
    entries = ctx.active_context.compatible_entries(SHAREPOINT_DRIVE_BINDING)
    choices = []
    for value in values[:25]:
        try:
            reference = SharePointDriveItemReference.model_validate(value)
        except ValueError:
            continue
        matching = [entry for entry in entries if entry.external_id == reference.drive_id]
        if len(matching) != 1:
            continue
        entry = matching[0]
        client = await drive_client_for_principal(
            ctx.db, actor=ctx.actor, workspace=ctx.workspace, entry=entry
        )
        try:
            item = item_result(
                await get_item(client, drive_id=entry.external_id, item_id=reference.item_id),
                drive_id=entry.external_id,
                operation="get_item",
            )
        except (IntegrationNotFoundError, IntegrationValidationError):
            continue
        choices.append(item_choice(entry, item))
    return tuple(choices)


SHAREPOINT_DRIVE_ITEM_RESOLVER = EntityResolverDefinition(
    entity_kind="sharepoint_drive_item",
    reference_type=SharePointDriveItemReference,
    search=search_items,
    resolve=resolve_items,
    max_page_size=25,
    max_exact_values=25,
    requires_active_context=True,
    provider_key="sharepoint",
)
