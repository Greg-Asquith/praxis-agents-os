# apps/api/integrations/meta_ads/tools/schemas/ad_edits.py

"""Input and result contracts for renaming, rescheduling, and changing the creative of existing ads."""

from typing import Literal, Self, get_args

from pydantic import Field, model_validator

from services.integrations.context.results import IntegrationFanOutEntry, IntegrationFanOutOutput

from ...creative_features import OFFERED_CHANGE_KEYS
from ...models import MetaAdsId, MetaAdsStrictModel, MetaAdsText
from ...references import MetaAdsAdReference, MetaAdsMediaReference, MetaAdsPostReference
from .ad_set_edits import MetaAdsSettingValue
from .ads import (
    MetaAdsAdName,
    MetaAdsAutomaticChangeKey,
    MetaAdsButton,
    MetaAdsCarouselCard,
    MetaAdsDescription,
    MetaAdsHeadline,
    MetaAdsLink,
    MetaAdsPrimaryText,
    MetaAdsUrlTags,
)
from .budget_schedules import MetaAdsLocalTime
from .objects import MetaAdsReviewState

MAX_AD_EDITS = 50
# Every setting an edit can change, in the order the card and results show them.
type MetaAdsAdSetting = Literal["name", "start_at", "end_at"]
AD_SETTINGS: tuple[MetaAdsAdSetting, ...] = get_args(MetaAdsAdSetting.__value__)

# "none" removes the ad's own time, so it follows its ad set's schedule again.
type MetaAdsAdTime = MetaAdsLocalTime | Literal["none"]


# What a creative change can set, in the order the card and results show them.
type MetaAdsCreativeField = Literal[
    "primary_text",
    "headline",
    "description",
    "link",
    "call_to_action",
    "url_tags",
    "media",
    "vertical_media",
    "thumbnail",
    "cards",
    "post",
    "automatic_changes",
]
CREATIVE_FIELDS: tuple[MetaAdsCreativeField, ...] = get_args(MetaAdsCreativeField.__value__)


class MetaAdsCreativeChanges(MetaAdsStrictModel):
    """What the ad says or shows; an omitted field keeps the live creative's value."""

    primary_text: MetaAdsPrimaryText | None = None
    headline: MetaAdsHeadline | None = None
    description: MetaAdsDescription | Literal["none"] | None = Field(
        default=None, description="Description, or none to remove it."
    )
    link: MetaAdsLink | None = None
    call_to_action: MetaAdsButton | None = None
    url_tags: MetaAdsUrlTags | Literal["none"] | None = Field(
        default=None, description="URL tags, or none to remove them."
    )
    media: MetaAdsMediaReference | None = Field(
        default=None, description="New image or ready video from the media library."
    )
    vertical_media: MetaAdsMediaReference | Literal["none"] | None = Field(
        default=None, description="New 9:16 version for Stories and Reels, or none to remove it."
    )
    thumbnail: MetaAdsMediaReference | None = Field(
        default=None, description="Image shown before a video ad plays."
    )
    cards: list[MetaAdsCarouselCard] | None = Field(
        default=None,
        min_length=2,
        max_length=10,
        description="Every carousel card, in order; replaces the current cards.",
    )
    post: MetaAdsPostReference | None = Field(
        default=None, description="For existing post ads: the post to run instead."
    )
    automatic_changes: list[MetaAdsAutomaticChangeKey] | None = Field(
        default=None,
        max_length=len(OFFERED_CHANGE_KEYS),
        description="Every automatic change that should be on; the rest are turned off.",
    )

    @model_validator(mode="after")
    def _one_change(self) -> Self:
        if not self.fields:
            raise ValueError("Name at least one part of the creative to change.")
        return self

    @property
    def fields(self) -> tuple[MetaAdsCreativeField, ...]:
        """The parts this change sets, in display order."""
        return tuple(key for key in CREATIVE_FIELDS if getattr(self, key) is not None)


class MetaAdsAdEdit(MetaAdsStrictModel):
    """New values for one ad; an omitted setting stays as it is."""

    ad: MetaAdsAdReference
    name: MetaAdsAdName | None = None
    start_at: MetaAdsAdTime | None = Field(
        default=None,
        description="When the ad starts, as YYYY-MM-DDTHH:MM in the account's time zone, or none.",
    )
    end_at: MetaAdsAdTime | None = Field(
        default=None,
        description="When the ad stops, as YYYY-MM-DDTHH:MM in the account's time zone, or none.",
    )
    creative: MetaAdsCreativeChanges | None = Field(
        default=None,
        description="Changes to what the ad says or shows; the ad switches to a new creative.",
    )

    @model_validator(mode="after")
    def _one_setting(self) -> Self:
        if not self.settings and self.creative is None:
            raise ValueError("Set at least one setting to change for each ad.")
        return self

    @property
    def settings(self) -> tuple[MetaAdsAdSetting, ...]:
        """The settings this edit changes, in display order."""
        return tuple(key for key in AD_SETTINGS if getattr(self, key) is not None)


class MetaAdsUpdateAdsRequest(MetaAdsStrictModel):
    """Every argument of an ad edit, so an edited approval is checked whole."""

    changes: list[MetaAdsAdEdit] = Field(min_length=1, max_length=MAX_AD_EDITS)

    @model_validator(mode="after")
    def _each_once(self) -> Self:
        ids = [(item.ad.account_id, item.ad.ad_id) for item in self.changes]
        if len(set(ids)) != len(ids):
            raise ValueError("List each ad once, with all its changes together.")
        return self


class MetaAdsAdSettingChange(MetaAdsStrictModel):
    setting: MetaAdsAdSetting
    # Null means not set: the ad follows its ad set's schedule.
    before: MetaAdsSettingValue | None
    requested: MetaAdsSettingValue | None
    # Read back after the change; null when not set, or when it couldn't be read.
    after: MetaAdsSettingValue | None


class MetaAdsCreativeOutcome(MetaAdsStrictModel):
    changed: list[MetaAdsCreativeField] = Field(max_length=len(CREATIVE_FIELDS))
    before_creative_id: MetaAdsId | None
    # Read back after the change; null when it couldn't be read.
    after_creative_id: MetaAdsId | None
    review: MetaAdsReviewState
    effective_status: MetaAdsText | None


class MetaAdsAdEditOutcome(MetaAdsStrictModel):
    ad_id: MetaAdsId
    name: MetaAdsText | None
    changes: list[MetaAdsAdSettingChange] = Field(max_length=len(AD_SETTINGS))
    creative: MetaAdsCreativeOutcome | None = None
    outcome: Literal["updated", "already_set", "failed", "unverified"]
    error_code: str | None = Field(default=None, max_length=100)
    message: str | None = Field(default=None, max_length=1000)


class MetaAdsUpdateAdsData(MetaAdsStrictModel):
    account_id: MetaAdsId
    # The IANA zone the times are in, such as Europe/London.
    time_zone: str = Field(max_length=64)
    ads: list[MetaAdsAdEditOutcome] = Field(max_length=MAX_AD_EDITS)


class MetaAdsUpdateAdsEntry(IntegrationFanOutEntry):
    data: MetaAdsUpdateAdsData | None = None


class MetaAdsUpdateAdsOutput(IntegrationFanOutOutput):
    results: list[MetaAdsUpdateAdsEntry]
