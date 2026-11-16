# apps/api/integrations/outlook_calendar/references.py

"""Scoped Outlook event references."""

from typing import ClassVar, Literal

from pydantic import Field

from services.integrations.entity_references import ScopedEntityReference


class OutlookEventReference(ScopedEntityReference):
    entity_kind: Literal["outlook_event"] = "outlook_event"
    calendar_id: str = Field(min_length=1, max_length=512)
    event_id: str = Field(min_length=1, max_length=512)
    identity_fields: ClassVar[tuple[str, ...]] = (
        *ScopedEntityReference.identity_fields,
        "calendar_id",
        "event_id",
    )

    @property
    def provider_scope_id(self) -> str:
        return self.calendar_id

    @property
    def provider_entity_id(self) -> str:
        return self.event_id
