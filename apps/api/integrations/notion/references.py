# apps/api/integrations/notion/references.py

"""Notion-owned scoped page and data-source references."""

from collections.abc import Mapping
from typing import Any, ClassVar, Literal

from pydantic import Field

from services.agents.runtime.untrusted import untrusted_content_text
from services.integrations.entity_references import ScopedEntityReference


class NotionPageReference(ScopedEntityReference):
    entity_kind: Literal["notion_page"] = "notion_page"
    workspace_id: str = Field(min_length=1, max_length=512, description="Notion workspace ID.")
    page_id: str = Field(min_length=1, max_length=512, description="Notion page ID.")
    identity_fields: ClassVar[tuple[str, ...]] = (
        *ScopedEntityReference.identity_fields,
        "workspace_id",
        "page_id",
    )

    @property
    def provider_scope_id(self) -> str:
        return self.workspace_id

    @property
    def provider_entity_id(self) -> str:
        return self.page_id


class NotionDataSourceReference(ScopedEntityReference):
    entity_kind: Literal["notion_data_source"] = "notion_data_source"
    workspace_id: str = Field(min_length=1, max_length=512, description="Notion workspace ID.")
    data_source_id: str = Field(min_length=1, max_length=512, description="Notion data source ID.")
    identity_fields: ClassVar[tuple[str, ...]] = (
        *ScopedEntityReference.identity_fields,
        "workspace_id",
        "data_source_id",
    )

    @property
    def provider_scope_id(self) -> str:
        return self.workspace_id

    @property
    def provider_entity_id(self) -> str:
        return self.data_source_id


def notion_page_reference(entry, payload: Mapping[str, Any]) -> NotionPageReference | None:
    page_id = str(payload.get("id", "")).strip()
    if not page_id:
        return None
    return notion_scoped_page_reference(
        entry,
        page_id=page_id,
        label=(untrusted_content_text(payload.get("title")) or "(untitled)")[:500],
    )


def notion_scoped_page_reference(
    entry,
    *,
    page_id: str,
    label: str,
) -> NotionPageReference:
    """Creates a scoped page reference from a validated Notion target."""
    return NotionPageReference(
        workspace_id=entry.external_id,
        page_id=page_id,
        label=label,
        description="Notion page",
        scope_label=entry.display_name,
    )


def notion_data_source_reference(
    entry, payload: Mapping[str, Any]
) -> NotionDataSourceReference | None:
    data_source_id = str(payload.get("id", "")).strip()
    if not data_source_id:
        return None
    return NotionDataSourceReference(
        workspace_id=entry.external_id,
        data_source_id=data_source_id,
        label=(untrusted_content_text(payload.get("title")) or "(untitled)")[:500],
        description="Notion data source",
        scope_label=entry.display_name,
    )
