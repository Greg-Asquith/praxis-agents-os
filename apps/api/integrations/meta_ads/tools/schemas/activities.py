# apps/api/integrations/meta_ads/tools/schemas/activities.py

"""Bounded change-history windows and typed Meta account activity."""

from datetime import date
from typing import Annotated

from pydantic import Field, model_validator

from services.integrations.context.results import IntegrationFanOutEntry, IntegrationFanOutOutput

from ...models import MetaAdsId, MetaAdsStrictModel, MetaAdsText

ACTIVITIES_MAX_EVENTS = 200
ACTIVITIES_MAX_DAYS = 31

type MetaAdsChangeValue = Annotated[str, Field(max_length=256)]


class MetaAdsActivitiesInput(MetaAdsStrictModel):
    since: date
    until: date
    object_ids: list[MetaAdsId] | None = Field(default=None, min_length=1, max_length=50)

    @model_validator(mode="after")
    def validate_window(self) -> "MetaAdsActivitiesInput":
        if self.since > self.until:
            raise ValueError("Set since on or before until.")
        if (self.until - self.since).days >= ACTIVITIES_MAX_DAYS:
            raise ValueError(f"Set a window of at most {ACTIVITIES_MAX_DAYS} days.")
        return self


class MetaAdsActivity(MetaAdsStrictModel):
    event_time: MetaAdsText
    event_type: MetaAdsText | None
    translated_event_type: MetaAdsText | None
    object_type: MetaAdsText | None
    object_id: MetaAdsId | None
    object_name: MetaAdsText | None
    actor_name: MetaAdsText | None
    old_value: MetaAdsChangeValue | None
    new_value: MetaAdsChangeValue | None


class MetaAdsActivitiesData(MetaAdsStrictModel):
    events: list[MetaAdsActivity]
    event_count: int = Field(ge=0)
    truncated: bool
    window_note: str | None
    timezone_name: MetaAdsText


class MetaAdsActivitiesEntry(IntegrationFanOutEntry):
    data: MetaAdsActivitiesData | None = None


class MetaAdsActivitiesOutput(IntegrationFanOutOutput):
    results: list[MetaAdsActivitiesEntry]
