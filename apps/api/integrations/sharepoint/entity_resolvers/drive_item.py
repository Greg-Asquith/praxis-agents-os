# apps/api/integrations/sharepoint/entity_resolvers/drive_item.py

"""Resolve known SharePoint item references within selected drives."""

from core.exceptions.integration import IntegrationNotFoundError, IntegrationValidationError
from services.integrations.entity_references import (
    EntityChoice,
    EntityResolverDefinition,
    EntityResolverPage,
)

from ..operations.get_item import get_item
from ..operations.utils import item_result
from ..references import SharePointDriveItemReference
from ..tools.utils import SHAREPOINT_DRIVE_BINDING, drive_client_for_principal


async def search_items(_ctx, _search, _dependent_args, _page_size, _cursor):
    return EntityResolverPage(choices=())


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
            )
        except (IntegrationNotFoundError, IntegrationValidationError):
            continue
        label = item["name"].content or "SharePoint item"
        choices.append(
            EntityChoice.from_reference(
                item["reference"].model_copy(
                    update={"label": label, "name": label, "scope_label": entry.display_name[:500]}
                ),
                icon="sharepoint",
            )
        )
    return tuple(choices)


SHAREPOINT_DRIVE_ITEM_RESOLVER = EntityResolverDefinition(
    entity_kind="sharepoint_drive_item",
    reference_type=SharePointDriveItemReference,
    search=search_items,
    resolve=resolve_items,
    max_page_size=25,
    requires_active_context=True,
    provider_key="sharepoint",
)
