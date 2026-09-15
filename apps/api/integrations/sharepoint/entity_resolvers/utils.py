# apps/api/integrations/sharepoint/entity_resolvers/utils.py

"""Builds bounded display choices from validated drive items."""

from services.integrations.entity_references import EntityChoice


def item_choice(entry, item: dict) -> EntityChoice:
    label = item["name"].content or "SharePoint item"
    return EntityChoice.from_reference(
        item["reference"].model_copy(
            update={
                "label": label,
                "name": label,
                "scope_label": entry.display_name[:500],
                "description": (
                    "Folder"
                    if item["kind"] == "folder"
                    else "File; choose a folder to list its contents."
                ),
            }
        ),
        icon="sharepoint",
    )
