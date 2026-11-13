# apps/api/integrations/google_ads/tools/schemas/performance_max.py

"""Arguments for a new Performance Max asset group, with Google's asset minimums."""

from collections.abc import Mapping, Sequence
from typing import Annotated, Literal, Protocol, Self

from pydantic import Field, field_validator, model_validator

from services.integrations.context.results import IntegrationFanOutEntry, IntegrationFanOutOutput

from ...references import (
    GoogleAdsAssetGroupReference,
    GoogleAdsAssetReference,
    GoogleAdsCampaignReference,
)
from .ad_groups import MAX_OBJECTS, MAX_RESULT_PROBLEMS
from .base import GoogleAdsStrictModel
from .positive_keywords import GoogleAdsFinalUrl

MAX_NEW_ASSET_GROUPS = 5
MAX_SEARCH_THEMES = 25
# Segments in one asset group's audience signal; enough for any signal an operator reads.
MAX_AUDIENCE_SEGMENTS = 20
MAX_LOGOS = 5
# The longest description Google accepts; at least one must also fit the short length.
SHORT_DESCRIPTION = 60

type GoogleAdsAssetGroupImageType = Literal[
    "MARKETING_IMAGE", "SQUARE_MARKETING_IMAGE", "PORTRAIT_MARKETING_IMAGE"
]
type GoogleAdsLogoType = Literal["LOGO", "LANDSCAPE_LOGO"]
# Google's audience segments; a combined audience can't be one.
type GoogleAdsSignalAudienceKind = Literal["user_list", "user_interest", "custom_audience"]

# Google's minimum and maximum of each asset type in one asset group.
ASSET_GROUP_LIMITS: Mapping[str, tuple[int, int]] = {
    "HEADLINE": (3, 15),
    "LONG_HEADLINE": (1, 5),
    "DESCRIPTION": (2, 5),
    "MARKETING_IMAGE": (1, 20),
    "SQUARE_MARKETING_IMAGE": (1, 20),
    "PORTRAIT_MARKETING_IMAGE": (0, 20),
    "YOUTUBE_VIDEO": (0, 15),
}
# What the card and refusals call each asset type that has a minimum.
ASSET_NOUNS: Mapping[str, str] = {
    "HEADLINE": "headline",
    "LONG_HEADLINE": "long headline",
    "DESCRIPTION": "description",
    "MARKETING_IMAGE": "landscape image",
    "SQUARE_MARKETING_IMAGE": "square image",
}


def single_spaced(value: object) -> object:
    return " ".join(value.split()) if isinstance(value, str) else value


def tidy_texts(value: object) -> object:
    """Collapses spaces in each text of a list and drops blank ones."""
    if not isinstance(value, list):
        return value
    return [single_spaced(item) for item in value if not isinstance(item, str) or item.strip()]


type AssetGroupHeadline = Annotated[str, Field(min_length=1, max_length=30)]
type AssetGroupLongText = Annotated[str, Field(min_length=1, max_length=90)]
type SearchThemeText = Annotated[str, Field(min_length=1, max_length=80)]


class GoogleAdsAssetGroupImage(GoogleAdsStrictModel):
    """An image already in the account, from google_ads_upload_media, and the shape it shows as."""

    asset: GoogleAdsAssetReference
    field_type: GoogleAdsAssetGroupImageType = Field(
        description=(
            "MARKETING_IMAGE (landscape 1.91:1), SQUARE_MARKETING_IMAGE (1:1), or "
            "PORTRAIT_MARKETING_IMAGE (4:5); one the upload's fits lists."
        )
    )

    @model_validator(mode="after")
    def _an_image(self) -> Self:
        if self.asset.asset_type != "IMAGE":
            raise ValueError("Choose an image asset.")
        return self


class GoogleAdsCampaignLogo(GoogleAdsStrictModel):
    asset: GoogleAdsAssetReference
    field_type: GoogleAdsLogoType = Field(
        default="LOGO", description="LOGO (square 1:1) or LANDSCAPE_LOGO (4:1)."
    )

    @model_validator(mode="after")
    def _an_image(self) -> Self:
        if self.asset.asset_type != "IMAGE":
            raise ValueError("Choose an image asset for the logo.")
        return self


class GoogleAdsAudienceSignal(GoogleAdsStrictModel):
    """An audience from google_ads_search_targeting that guides Google, without limiting reach."""

    kind: GoogleAdsSignalAudienceKind
    key: Annotated[str, Field(pattern=r"^[0-9]{1,20}$")]
    # For display until Google's own name is read back.
    name: str | None = Field(default=None, max_length=500)


class _GroupAssets(Protocol):
    @property
    def headlines(self) -> Sequence[str]: ...
    @property
    def long_headlines(self) -> Sequence[str]: ...
    @property
    def descriptions(self) -> Sequence[str]: ...
    @property
    def images(self) -> Sequence[GoogleAdsAssetGroupImage]: ...
    @property
    def videos(self) -> Sequence[GoogleAdsAssetReference]: ...


def repeated_problem(
    assets: _GroupAssets,
    themes: Sequence[str] = (),
    audiences: Sequence[GoogleAdsAudienceSignal] = (),
) -> str | None:
    """Says what's listed twice, or that a video isn't a YouTube video, or None."""
    for label, texts in (
        ("headline", assets.headlines),
        ("long headline", assets.long_headlines),
        ("description", assets.descriptions),
        ("search theme", [theme.casefold() for theme in themes]),
    ):
        if len(set(texts)) != len(texts):
            return f"each {label} must be different."
    images = [(image.asset.asset_id, image.field_type) for image in assets.images]
    if len(set(images)) != len(images):
        return "list each image once for each shape."
    if any(video.asset_type != "YOUTUBE_VIDEO" for video in assets.videos):
        return "videos must be YouTube video assets."
    if len({video.asset_id for video in assets.videos}) != len(assets.videos):
        return "list each video once."
    if len({(item.kind, item.key) for item in audiences}) != len(audiences):
        return "list each audience signal once."
    return None


class GoogleAdsNewAssetGroup(GoogleAdsStrictModel):
    """One asset group: its landing page, the text and media Google mixes into ads, and themes."""

    name: str = Field(min_length=1, max_length=255)
    final_url: GoogleAdsFinalUrl = Field(
        description="A live page on the advertiser's own site. Never guess a domain."
    )
    headlines: list[AssetGroupHeadline] = Field(default_factory=list, max_length=15)
    long_headlines: list[AssetGroupLongText] = Field(default_factory=list, max_length=5)
    descriptions: list[AssetGroupLongText] = Field(default_factory=list, max_length=5)
    images: list[GoogleAdsAssetGroupImage] = Field(default_factory=list, max_length=60)
    videos: list[GoogleAdsAssetReference] = Field(
        default_factory=list, max_length=15, description="YouTube video assets."
    )
    search_themes: list[SearchThemeText] = Field(default_factory=list, max_length=MAX_SEARCH_THEMES)
    audience_signals: list[GoogleAdsAudienceSignal] = Field(
        default_factory=list,
        max_length=MAX_AUDIENCE_SEGMENTS,
        description=(
            "Your-data lists, interests, and custom audiences, from google_ads_search_targeting. "
            "Google reads them as one signal: people in any of them."
        ),
    )

    @field_validator("name", mode="before")
    @classmethod
    def _normalise_name(cls, value: object) -> object:
        return single_spaced(value)

    @field_validator("headlines", "long_headlines", "descriptions", "search_themes", mode="before")
    @classmethod
    def _tidy_texts(cls, value: object) -> object:
        return tidy_texts(value)

    @model_validator(mode="after")
    def _distinct(self) -> Self:
        if problem := repeated_problem(self, self.search_themes, self.audience_signals):
            raise ValueError(f"{self.name}: {problem}")
        return self

    @property
    def counts(self) -> dict[str, int]:
        """How many assets of each type the group links."""
        counts = {
            "HEADLINE": len(self.headlines),
            "LONG_HEADLINE": len(self.long_headlines),
            "DESCRIPTION": len(self.descriptions),
            "YOUTUBE_VIDEO": len(self.videos),
        }
        for field_type in ("MARKETING_IMAGE", "SQUARE_MARKETING_IMAGE", "PORTRAIT_MARKETING_IMAGE"):
            counts[field_type] = sum(image.field_type == field_type for image in self.images)
        return counts

    @property
    def has_assets(self) -> bool:
        return any(self.counts.values())

    @property
    def object_count(self) -> int:
        """The group, its filter, and at most an asset and a link for each text, plus the rest.

        An audience signal is an audience and a signal, however many segments it holds.
        """
        texts = len(self.headlines) + len(self.long_headlines) + len(self.descriptions)
        signal = 2 if self.audience_signals else 0
        return (
            2 + 2 * texts + len(self.images) + len(self.videos) + len(self.search_themes) + signal
        )


def asset_group_problems(group: GoogleAdsNewAssetGroup, *, retail: bool) -> list[str]:
    """What Google needs before it accepts the group, as the card shows it.

    Args:
        retail: True when the campaign shows a Merchant Center feed's products. Google then
            makes the group's assets from the feed when it links none of its own.
    """
    if retail and not group.has_assets:
        return []
    problems = []
    counts = group.counts
    for field_type, noun in ASSET_NOUNS.items():
        minimum, maximum = ASSET_GROUP_LIMITS[field_type]
        if counts[field_type] < minimum:
            problems.append(
                f"{group.name}: needs at least {minimum} {noun}{'s' if minimum > 1 else ''}, "
                f"has {counts[field_type]}."
            )
        elif counts[field_type] > maximum:
            problems.append(f"{group.name}: takes at most {maximum} {noun}s.")
    if group.descriptions and all(len(item) > SHORT_DESCRIPTION for item in group.descriptions):
        problems.append(
            f"{group.name}: needs one description of {SHORT_DESCRIPTION} characters or fewer."
        )
    return problems


type GoogleAdsBuildOutcome = Literal["created", "failed", "unverified"]


class GoogleAdsCreatedAssetGroup(GoogleAdsStrictModel):
    name: str
    outcome: GoogleAdsBuildOutcome
    # Set when created, for the agent to pass to other tools.
    reference: GoogleAdsAssetGroupReference | None = None
    headlines: int = Field(ge=0)
    long_headlines: int = Field(ge=0)
    descriptions: int = Field(ge=0)
    images: int = Field(ge=0)
    videos: int = Field(ge=0)
    search_themes: int = Field(ge=0)
    audience_signals: int = Field(default=0, ge=0)


class GoogleAdsCreateAssetGroupsRequest(GoogleAdsStrictModel):
    """Every argument of an asset group creation, so an edited approval is checked whole."""

    campaign: GoogleAdsCampaignReference
    asset_groups: list[GoogleAdsNewAssetGroup] = Field(
        min_length=1, max_length=MAX_NEW_ASSET_GROUPS
    )
    status: Literal["PAUSED", "ENABLED"] = "PAUSED"

    @model_validator(mode="after")
    def _whole_request(self) -> Self:
        names = [group.name.casefold() for group in self.asset_groups]
        if len(set(names)) != len(names):
            raise ValueError("Give each new asset group a different name.")
        if sum(group.object_count for group in self.asset_groups) > MAX_OBJECTS:
            raise ValueError(f"One request can create at most {MAX_OBJECTS:,} objects.")
        return self


type GoogleAdsAssetGroupBuildKind = Literal[
    "asset_group",
    "listing_filter",
    "text_asset",
    "asset_group_link",
    "search_theme",
    "audience",
    "audience_signal",
]


class GoogleAdsAssetGroupKindCount(GoogleAdsStrictModel):
    kind: GoogleAdsAssetGroupBuildKind
    created: int = Field(ge=0)
    failed: int = Field(ge=0)
    unverified: int = Field(ge=0)


class GoogleAdsAssetGroupProblemRow(GoogleAdsStrictModel):
    item: str
    kind: GoogleAdsAssetGroupBuildKind
    message: str
    error_code: str | None = None


class GoogleAdsCreateAssetGroupsData(GoogleAdsStrictModel):
    account_id: str
    campaign_name: str
    requested_status: Literal["PAUSED", "ENABLED"]
    kinds: list[GoogleAdsAssetGroupKindCount] = Field(max_length=7)
    asset_groups: list[GoogleAdsCreatedAssetGroup] = Field(max_length=MAX_NEW_ASSET_GROUPS)
    problems: list[GoogleAdsAssetGroupProblemRow] = Field(max_length=MAX_RESULT_PROBLEMS)


class GoogleAdsCreateAssetGroupsEntry(IntegrationFanOutEntry):
    data: GoogleAdsCreateAssetGroupsData | None = None


class GoogleAdsCreateAssetGroupsOutput(IntegrationFanOutOutput):
    results: list[GoogleAdsCreateAssetGroupsEntry]
