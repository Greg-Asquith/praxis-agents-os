# apps/api/integrations/meta_ads/tools/schemas/delivery.py

"""How an ad set counts results, how often people see it, and when it runs."""

import json
from typing import Literal, Self

from pydantic import Field, model_validator

from ...models import MetaAdsStrictModel

type MetaAdsWeekday = Literal[
    "sunday", "monday", "tuesday", "wednesday", "thursday", "friday", "saturday"
]
# Meta numbers days from 0 for Sunday.
WEEKDAYS: tuple[MetaAdsWeekday, ...] = (
    "sunday",
    "monday",
    "tuesday",
    "wednesday",
    "thursday",
    "friday",
    "saturday",
)
MAX_SCHEDULE_WINDOWS = 7


class MetaAdsAttribution(MetaAdsStrictModel):
    """Days after a click, view, or engaged video view in which a result counts; 0 for none."""

    click_days: int = Field(ge=1, le=90, description="1 or 7.")
    view_days: int = Field(default=0, ge=0, le=90, description="0 or 1.")
    engaged_view_days: int = Field(
        default=0, ge=0, le=90, description="0 or 1; counts video ads watched for 5 seconds."
    )


class MetaAdsFrequencyCap(MetaAdsStrictModel):
    max_impressions: int = Field(ge=1, le=90, description="Most times one person sees the ads.")
    every_days: int = Field(ge=1, le=90, description="In this many days.")


class MetaAdsScheduleWindow(MetaAdsStrictModel):
    days: list[MetaAdsWeekday] = Field(min_length=1, max_length=7)
    start_hour: int = Field(ge=0, le=23)
    # 24 runs to midnight.
    end_hour: int = Field(ge=1, le=24)

    @model_validator(mode="after")
    def _check_window(self) -> Self:
        if self.end_hour <= self.start_hour:
            raise ValueError("Set end_hour after start_hour.")
        if len(set(self.days)) != len(self.days):
            raise ValueError("List each day once in a window.")
        return self


class MetaAdsAdSchedule(MetaAdsStrictModel):
    """Hours the ads run each week; viewer hours follow each person's own time zone."""

    time_zone: Literal["viewer", "account"] = "viewer"
    windows: list[MetaAdsScheduleWindow] = Field(min_length=1, max_length=MAX_SCHEDULE_WINDOWS)

    @model_validator(mode="after")
    def _no_overlap(self) -> Self:
        hours: set[tuple[str, int]] = set()
        for window in self.windows:
            for day in window.days:
                taken = {(day, hour) for hour in range(window.start_hour, window.end_hour)}
                if hours & taken:
                    raise ValueError("Time windows on the same day can't overlap.")
                hours |= taken
        return self


def canonical(value: MetaAdsAttribution | MetaAdsFrequencyCap | MetaAdsAdSchedule) -> str:
    """One text form per setting value, so a request and a read-back compare as equal."""
    if isinstance(value, MetaAdsAdSchedule):
        windows = sorted(
            (
                {
                    "days": sorted(window.days, key=WEEKDAYS.index),
                    "start_hour": window.start_hour,
                    "end_hour": window.end_hour,
                }
                for window in value.windows
            ),
            key=lambda item: (WEEKDAYS.index(item["days"][0]), item["start_hour"]),
        )
        return json.dumps({"time_zone": value.time_zone, "windows": windows}, separators=(",", ":"))
    return json.dumps(value.model_dump(mode="json"), separators=(",", ":"))
