# apps/api/integrations/google_ads/tools/schemas/asset_group_updates.py

"""Arguments and result contract for changing live Performance Max asset groups."""

from typing import Literal, Self

from pydantic import Field, field_validator, model_validator

from services.integrations.context.results import IntegrationFanOutEntry, IntegrationFanOutOutput

from ...operations.asset_group_state import MAX_ASSET_GROUP_READ
from ...references import GoogleAdsAssetGroupReference, GoogleAdsAssetReference
from .ad_groups import MAX_OBJECTS
from .assets import GoogleAdsAssetCounts
from .base import GoogleAdsStrictModel
from .performance_max import (
    MAX_AUDIENCE_SEGMENTS,
    MAX_SEARCH_THEMES,
    AssetGroupHeadline,
    AssetGroupLongText,
    GoogleAdsAssetGroupImage,
    GoogleAdsAudienceSignal,
    SearchThemeText,
    repeated_problem,
    single_spaced,
    tidy_texts,
)
from .positive_keywords import GoogleAdsFinalUrl

MAX_ASSET_GROUP_UPDATES = MAX_ASSET_GROUP_READ

type GoogleAdsAssetGroupChangeKind = Literal[
    "name",
    "final_url",
    "HEADLINE",
    "LONG_HEADLINE",
    "DESCRIPTION",
    "MARKETING_IMAGE",
    "SQUARE_MARKETING_IMAGE",
    "PORTRAIT_MARKETING_IMAGE",
    "YOUTUBE_VIDEO",
    "search_theme",
    "audience_signal",
]
type GoogleAdsAssetGroupChangeOutcome = Literal[
    "added", "removed", "changed", "already_set", "not_found", "failed", "unverified"
]


class GoogleAdsAssetGroupAssets(GoogleAdsStrictModel):
    """Text to add or take out, and images and videos from google_ads_upload_media."""

    headlines: list[AssetGroupHeadline] = Field(default_factory=list, max_length=15)
    long_headlines: list[AssetGroupLongText] = Field(default_factory=list, max_length=5)
    descriptions: list[AssetGroupLongText] = Field(default_factory=list, max_length=5)
    images: list[GoogleAdsAssetGroupImage] = Field(default_factory=list, max_length=60)
    videos: list[GoogleAdsAssetReference] = Field(
        default_factory=list, max_length=15, description="YouTube video assets."
    )

    @field_validator("headlines", "long_headlines", "descriptions", mode="before")
    @classmethod
    def _tidy_texts(cls, value: object) -> object:
        return tidy_texts(value)

    @property
    def items(self) -> list[tuple[str, str]]:
        """Each text by its field type, then each image and video by its asset ID."""
        return [
            *(("HEADLINE", text) for text in self.headlines),
            *(("LONG_HEADLINE", text) for text in self.long_headlines),
            *(("DESCRIPTION", text) for text in self.descriptions),
            *((image.field_type, image.asset.asset_id) for image in self.images),
            *(("YOUTUBE_VIDEO", video.asset_id) for video in self.videos),
        ]


class GoogleAdsAssetGroupUpdate(GoogleAdsStrictModel):
    """One live asset group and only what changes in it."""

    asset_group: GoogleAdsAssetGroupReference
    name: str | None = Field(default=None, min_length=1, max_length=255)
    final_url: GoogleAdsFinalUrl | None = Field(
        default=None, description="A live page on the advertiser's own site. Never guess one."
    )
    add_assets: GoogleAdsAssetGroupAssets = Field(default_factory=GoogleAdsAssetGroupAssets)
    remove_assets: GoogleAdsAssetGroupAssets = Field(default_factory=GoogleAdsAssetGroupAssets)
    add_search_themes: list[SearchThemeText] = Field(
        default_factory=list, max_length=MAX_SEARCH_THEMES
    )
    remove_search_themes: list[SearchThemeText] = Field(
        default_factory=list, max_length=MAX_SEARCH_THEMES
    )
    add_audience_signals: list[GoogleAdsAudienceSignal] = Field(
        default_factory=list, max_length=MAX_AUDIENCE_SEGMENTS
    )
    remove_audience_signals: list[GoogleAdsAudienceSignal] = Field(
        default_factory=list, max_length=MAX_AUDIENCE_SEGMENTS
    )

    @field_validator("name", mode="before")
    @classmethod
    def _normalise_name(cls, value: object) -> object:
        return single_spaced(value)

    @field_validator("add_search_themes", "remove_search_themes", mode="before")
    @classmethod
    def _tidy_themes(cls, value: object) -> object:
        return tidy_texts(value)

    @model_validator(mode="after")
    def _one_way(self) -> Self:
        label = self.asset_group.label or self.asset_group.asset_group_id
        if self.item_count == 0 and self.name is None and self.final_url is None:
            raise ValueError(f"{label}: say what changes in the asset group.")
        for noun, added, removed in (
            ("asset", self.add_assets.items, self.remove_assets.items),
            (
                "search theme",
                [theme.casefold() for theme in self.add_search_themes],
                [theme.casefold() for theme in self.remove_search_themes],
            ),
            (
                "audience signal",
                [(item.kind, item.key) for item in self.add_audience_signals],
                [(item.kind, item.key) for item in self.remove_audience_signals],
            ),
        ):
            if set(added) & set(removed):
                raise ValueError(f"{label}: add or remove each {noun}, not both.")
        if problem := repeated_problem(
            self.add_assets, self.add_search_themes, self.add_audience_signals
        ):
            raise ValueError(f"{label}: {problem}")
        if problem := repeated_problem(
            self.remove_assets, self.remove_search_themes, self.remove_audience_signals
        ):
            raise ValueError(f"{label}: {problem}")
        return self

    @property
    def item_count(self) -> int:
        return (
            len(self.add_assets.items)
            + len(self.remove_assets.items)
            + len(self.add_search_themes)
            + len(self.remove_search_themes)
            + len(self.add_audience_signals)
            + len(self.remove_audience_signals)
        )


class GoogleAdsUpdateAssetGroupsRequest(GoogleAdsStrictModel):
    """Every argument of an asset group update, so an edited approval is checked whole."""

    entries: list[GoogleAdsAssetGroupUpdate] = Field(
        min_length=1, max_length=MAX_ASSET_GROUP_UPDATES
    )

    @model_validator(mode="after")
    def _whole_request(self) -> Self:
        groups = [entry.asset_group.resource_name for entry in self.entries]
        if len(set(groups)) != len(groups):
            raise ValueError("Give each asset group one entry.")
        if sum(entry.item_count for entry in self.entries) > MAX_OBJECTS:
            raise ValueError(f"One request can make at most {MAX_OBJECTS:,} changes.")
        return self


class GoogleAdsAssetGroupChangeRow(GoogleAdsStrictModel):
    asset_group_name: str
    campaign_name: str | None = None
    action: Literal["add", "remove", "set"]
    kind: GoogleAdsAssetGroupChangeKind
    # The text, URL, name, or asset the change is about.
    item: str
    # The name or URL it replaces, for a setting.
    before: str | None = None
    outcome: GoogleAdsAssetGroupChangeOutcome
    error_code: str | None = None
    message: str | None = None


class GoogleAdsUpdateAssetGroupsData(GoogleAdsStrictModel):
    account_id: str
    counts: GoogleAdsAssetCounts
    outcomes: list[GoogleAdsAssetGroupChangeRow]
    outcomes_truncated: bool = False


class GoogleAdsUpdateAssetGroupsEntry(IntegrationFanOutEntry):
    data: GoogleAdsUpdateAssetGroupsData | None = None


class GoogleAdsUpdateAssetGroupsOutput(IntegrationFanOutOutput):
    results: list[GoogleAdsUpdateAssetGroupsEntry]
