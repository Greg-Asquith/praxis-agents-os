# apps/api/integrations/sharepoint/references.py

"""Drive-scoped SharePoint file and folder references."""

from typing import ClassVar, Literal

from pydantic import Field

from services.integrations.entity_references import ScopedEntityReference


class SharePointDriveItemReference(ScopedEntityReference):
    entity_kind: Literal["sharepoint_drive_item"] = "sharepoint_drive_item"
    label: str = Field(default="SharePoint item", min_length=1, max_length=500)
    drive_id: str = Field(min_length=1, max_length=512, pattern=r"^[^/\\?#\s]+$")
    item_id: str = Field(min_length=1, max_length=512, pattern=r"^[^/\\?#\s]+$")
    name: str | None = Field(default=None, max_length=500)
    kind: Literal["file", "folder"] | None = None
    identity_fields: ClassVar[tuple[str, ...]] = (
        *ScopedEntityReference.identity_fields,
        "drive_id",
        "item_id",
    )

    @property
    def provider_scope_id(self) -> str:
        return self.drive_id

    @property
    def provider_entity_id(self) -> str:
        return self.item_id
