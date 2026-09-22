# apps/api/integrations/sharepoint/entity_resolvers/utils.py

"""Builds bounded display choices from validated drive items."""

from services.integrations.entity_references import EntityChoice


def item_choice(entry, item: dict) -> EntityChoice:
    label = item["name"].content or "SharePoint item"
    parent_path = item["path"].content.split("root:", 1)[-1].rstrip("/")
    kind = "Folder" if item["kind"] == "folder" else "File; choose a folder to list its contents."
    description = f"{kind}\n{parent_path}/{label}"
    return EntityChoice.from_reference(
        item["reference"].model_copy(
            update={
                "label": label,
                "name": label,
                "scope_label": entry.display_name[:500],
                "description": description if len(description) <= 1000 else description[:999] + "…",
            }
        ),
        icon="sharepoint",
    )
