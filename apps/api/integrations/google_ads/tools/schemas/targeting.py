# apps/api/integrations/google_ads/tools/schemas/targeting.py

"""Arguments and result contracts for finding and changing Google Ads targeting."""

from itertools import pairwise
from typing import Annotated, Literal, Self

from pydantic import Field, model_validator

from services.integrations.context.results import IntegrationFanOutEntry, IntegrationFanOutOutput

from ...references import GoogleAdsCampaignReference
from .base import GoogleAdsStrictModel

MAX_TARGETING_CHANGES = 20
MAX_TARGETING_ITEMS = 2_400
MAX_TARGETING_RESULTS = 100
# One row per campaign, setting, action, and outcome, so results stay small at any request size.
_MAX_OUTCOME_ROWS = 1_600
_MAX_OUTCOME_ITEMS = 10

type GoogleAdsTargetingKind = Literal["location", "language"]
type GoogleAdsLocationSetting = Literal["PRESENCE_OR_INTEREST", "PRESENCE"]
type GoogleAdsRadiusUnits = Literal["MILES", "KILOMETERS"]
type GoogleAdsTargetingSetting = Literal[
    "locations",
    "excluded_locations",
    "radius",
    "languages",
    "location_setting",
    "devices",
    "ad_schedule",
]
type GoogleAdsDevice = Literal["MOBILE", "DESKTOP", "TABLET"]
type GoogleAdsDay = Literal[
    "MONDAY", "TUESDAY", "WEDNESDAY", "THURSDAY", "FRIDAY", "SATURDAY", "SUNDAY"
]
# Percent, as the card shows it. Google accepts modifiers from 0.1 to 10.0.
type GoogleAdsBidAdjustment = Annotated[int, Field(ge=-90, le=900)]
type _Key = Annotated[str, Field(pattern=r"^[0-9]{1,20}$")]
# Quarter hours in the account's time zone; a window can end at 24:00.
type _Start = Annotated[str, Field(pattern=r"^([01][0-9]|2[0-3]):(00|15|30|45)$")]
type _End = Annotated[str, Field(pattern=r"^(([01][0-9]|2[0-3]):(00|15|30|45)|24:00)$")]
# Google allows six windows a day.
MAX_WINDOWS_PER_DAY = 6


class GoogleAdsTargetingOption(GoogleAdsStrictModel):
    kind: GoogleAdsTargetingKind
    # What google_ads_update_targeting takes; the name is for display only.
    key: _Key
    name: str = Field(min_length=1, max_length=500)
    target_type: str | None = Field(default=None, max_length=64)
    region: str | None = Field(default=None, max_length=500)
    country_code: str | None = Field(default=None, max_length=8)
    reach: int | None = Field(default=None, ge=0)
    search_term: str | None = Field(default=None, max_length=500)


class GoogleAdsTargetingSearchData(GoogleAdsStrictModel):
    options: list[GoogleAdsTargetingOption] = Field(max_length=MAX_TARGETING_RESULTS)
    truncated: bool


class GoogleAdsTargetingSearchEntry(IntegrationFanOutEntry):
    data: GoogleAdsTargetingSearchData | None = None


class GoogleAdsTargetingSearchOutput(IntegrationFanOutOutput):
    results: list[GoogleAdsTargetingSearchEntry]


class GoogleAdsTarget(GoogleAdsStrictModel):
    key: _Key
    # For display until Google's own name is read back.
    name: str | None = Field(default=None, max_length=500)
    target_type: str | None = Field(default=None, max_length=64)


class GoogleAdsLocationTarget(GoogleAdsTarget):
    # Leaves a location already targeted at its current adjustment when null.
    bid_adjustment: GoogleAdsBidAdjustment | None = None


class GoogleAdsRadiusTarget(GoogleAdsStrictModel):
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    radius: float = Field(gt=0)
    units: GoogleAdsRadiusUnits
    # Names the place on the card; Google doesn't read it.
    label: str | None = Field(default=None, max_length=200)
    bid_adjustment: GoogleAdsBidAdjustment | None = None


class GoogleAdsDeviceTarget(GoogleAdsStrictModel):
    device: GoogleAdsDevice
    # 0 clears the adjustment. Leave null when excluding the device.
    bid_adjustment: GoogleAdsBidAdjustment | None = None
    excluded: bool = False

    @model_validator(mode="after")
    def _adjust_or_exclude(self) -> Self:
        if self.excluded == (self.bid_adjustment is not None):
            raise ValueError("Give each device a bid_adjustment, or set excluded, not both.")
        return self


class GoogleAdsScheduleWindow(GoogleAdsStrictModel):
    day: GoogleAdsDay
    start: _Start
    end: _End
    bid_adjustment: GoogleAdsBidAdjustment | None = None

    @model_validator(mode="after")
    def _starts_before_it_ends(self) -> Self:
        # Zero-padded times compare in clock order.
        if self.start >= self.end:
            raise ValueError("Each ad schedule window must start before it ends.")
        return self


def _check_windows(windows: list[GoogleAdsScheduleWindow]) -> None:
    by_day: dict[str, list[GoogleAdsScheduleWindow]] = {}
    for window in windows:
        by_day.setdefault(window.day, []).append(window)
    for day, items in by_day.items():
        if len(items) > MAX_WINDOWS_PER_DAY:
            raise ValueError(
                f"Google Ads allows {MAX_WINDOWS_PER_DAY} ad schedule windows a day; "
                f"{day.title()} has {len(items)}."
            )
        items.sort(key=lambda item: item.start)
        for before, after in pairwise(items):
            if after.start < before.end:
                raise ValueError(
                    f"Ad schedule windows on {day.title()} overlap. Each time can be in one "
                    "window only."
                )


class GoogleAdsTargetingChange(GoogleAdsStrictModel):
    """What changes on one campaign, as additions and removals."""

    campaign: GoogleAdsCampaignReference
    add_locations: list[GoogleAdsLocationTarget] = Field(default_factory=list)
    exclude_locations: list[GoogleAdsTarget] = Field(default_factory=list)
    remove_locations: list[GoogleAdsTarget] = Field(default_factory=list)
    add_radius: list[GoogleAdsRadiusTarget] = Field(default_factory=list)
    remove_radius: list[_Key] = Field(default_factory=list)
    location_setting: GoogleAdsLocationSetting | None = None
    add_languages: list[GoogleAdsTarget] = Field(default_factory=list)
    remove_languages: list[GoogleAdsTarget] = Field(default_factory=list)
    devices: list[GoogleAdsDeviceTarget] = Field(default_factory=list, max_length=3)
    # The campaign's whole weekly schedule after the change, not only what changes.
    ad_schedule: list[GoogleAdsScheduleWindow] | None = Field(
        default=None, min_length=1, max_length=7 * MAX_WINDOWS_PER_DAY
    )
    # Removes every window, so ads can show at any time.
    clear_ad_schedule: bool = False

    @property
    def item_count(self) -> int:
        return (
            len(self.add_locations)
            + len(self.exclude_locations)
            + len(self.remove_locations)
            + len(self.add_radius)
            + len(self.remove_radius)
            + len(self.add_languages)
            + len(self.remove_languages)
            + int(self.location_setting is not None)
            + len(self.devices)
            + len(self.ad_schedule or ())
            + int(self.clear_ad_schedule)
        )

    @model_validator(mode="after")
    def _each_item_once(self) -> Self:
        if self.item_count == 0:
            raise ValueError("Each campaign needs at least one targeting change.")
        locations = [
            item.key
            for items in (self.add_locations, self.exclude_locations, self.remove_locations)
            for item in items
        ]
        languages = [
            item.key for items in (self.add_languages, self.remove_languages) for item in items
        ]
        radii = [
            (item.latitude, item.longitude, item.radius, item.units) for item in self.add_radius
        ]
        for items in (locations, languages, radii, self.remove_radius):
            if len(set(items)) != len(items):
                raise ValueError("List each location, radius, and language once per campaign.")
        devices = [item.device for item in self.devices]
        if len(set(devices)) != len(devices):
            raise ValueError("List each device once per campaign.")
        if self.ad_schedule is not None and self.clear_ad_schedule:
            raise ValueError("Set ad_schedule or clear_ad_schedule, not both.")
        _check_windows(self.ad_schedule or [])
        return self


class GoogleAdsUpdateTargetingRequest(GoogleAdsStrictModel):
    """Every argument of a targeting change, so an edited approval is checked whole."""

    changes: list[GoogleAdsTargetingChange] = Field(min_length=1, max_length=MAX_TARGETING_CHANGES)

    @model_validator(mode="after")
    def _within_limits(self) -> Self:
        campaigns = [
            (change.campaign.customer_id, change.campaign.campaign_id) for change in self.changes
        ]
        if len(set(campaigns)) != len(campaigns):
            raise ValueError("List each campaign once.")
        if sum(change.item_count for change in self.changes) > MAX_TARGETING_ITEMS:
            raise ValueError(f"One request can make at most {MAX_TARGETING_ITEMS:,} changes.")
        return self


class GoogleAdsTargetingOutcomeItem(GoogleAdsStrictModel):
    name: str
    bid_adjustment: int | None = None
    # The adjustment before a change to it.
    previous_bid_adjustment: int | None = None


class GoogleAdsTargetingOutcome(GoogleAdsStrictModel):
    campaign_id: str
    campaign_name: str
    setting: GoogleAdsTargetingSetting
    action: Literal["add", "remove", "change_bid", "set"]
    outcome: Literal["updated", "already_set", "failed", "unverified"]
    count: int = Field(ge=1)
    # The first few items in this row; `count` is the total.
    items: list[GoogleAdsTargetingOutcomeItem] = Field(max_length=_MAX_OUTCOME_ITEMS)
    error_code: str | None = None
    # The first reason in this row.
    message: str | None = None


class GoogleAdsUpdateTargetingData(GoogleAdsStrictModel):
    account_id: str
    outcomes: list[GoogleAdsTargetingOutcome] = Field(max_length=_MAX_OUTCOME_ROWS)


class GoogleAdsUpdateTargetingEntry(IntegrationFanOutEntry):
    data: GoogleAdsUpdateTargetingData | None = None


class GoogleAdsUpdateTargetingOutput(IntegrationFanOutOutput):
    results: list[GoogleAdsUpdateTargetingEntry]
