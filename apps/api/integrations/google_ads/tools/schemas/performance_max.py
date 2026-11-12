# apps/api/integrations/google_ads/tools/schemas/performance_max.py

"""Arguments for a new Performance Max asset group, with Google's asset minimums."""

from collections.abc import Mapping
from typing import Annotated, Literal, Self

from pydantic import Field, field_validator, model_validator

from ...references import GoogleAdsAssetGroupReference, GoogleAdsAssetReference
from .base import GoogleAdsStrictModel
from .positive_keywords import GoogleAdsFinalUrl

MAX_NEW_ASSET_GROUPS = 5
MAX_SEARCH_THEMES = 25
MAX_LOGOS = 5
# The longest description Google accepts; at least one must also fit the short length.
SHORT_DESCRIPTION = 60

type GoogleAdsAssetGroupImageType = Literal[
    "MARKETING_IMAGE", "SQUARE_MARKETING_IMAGE", "PORTRAIT_MARKETING_IMAGE"
]
type GoogleAdsLogoType = Literal["LOGO", "LANDSCAPE_LOGO"]

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
_NOUNS = {
    "HEADLINE": "headline",
    "LONG_HEADLINE": "long headline",
    "DESCRIPTION": "description",
    "MARKETING_IMAGE": "landscape image",
    "SQUARE_MARKETING_IMAGE": "square image",
}


def _single_spaced(value: object) -> object:
    return " ".join(value.split()) if isinstance(value, str) else value


type _Headline = Annotated[str, Field(min_length=1, max_length=30)]
type _LongText = Annotated[str, Field(min_length=1, max_length=90)]
type _SearchTheme = Annotated[str, Field(min_length=1, max_length=80)]


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


class GoogleAdsNewAssetGroup(GoogleAdsStrictModel):
    """One asset group: its landing page, the text and media Google mixes into ads, and themes."""

    name: str = Field(min_length=1, max_length=255)
    final_url: GoogleAdsFinalUrl = Field(
        description="A live page on the advertiser's own site. Never guess a domain."
    )
    headlines: list[_Headline] = Field(default_factory=list, max_length=15)
    long_headlines: list[_LongText] = Field(default_factory=list, max_length=5)
    descriptions: list[_LongText] = Field(default_factory=list, max_length=5)
    images: list[GoogleAdsAssetGroupImage] = Field(default_factory=list, max_length=60)
    videos: list[GoogleAdsAssetReference] = Field(
        default_factory=list, max_length=15, description="YouTube video assets."
    )
    search_themes: list[_SearchTheme] = Field(default_factory=list, max_length=MAX_SEARCH_THEMES)

    @field_validator("name", mode="before")
    @classmethod
    def _normalise_name(cls, value: object) -> object:
        return _single_spaced(value)

    @field_validator("headlines", "long_headlines", "descriptions", "search_themes", mode="before")
    @classmethod
    def _tidy_texts(cls, value: object) -> object:
        if not isinstance(value, list):
            return value
        return [_single_spaced(item) for item in value if not isinstance(item, str) or item.strip()]

    @model_validator(mode="after")
    def _distinct(self) -> Self:
        for label, texts in (
            ("headline", self.headlines),
            ("long headline", self.long_headlines),
            ("description", self.descriptions),
            ("search theme", [theme.casefold() for theme in self.search_themes]),
        ):
            if len(set(texts)) != len(texts):
                raise ValueError(f"{self.name}: each {label} must be different.")
        images = [(image.asset.asset_id, image.field_type) for image in self.images]
        if len(set(images)) != len(images):
            raise ValueError(f"{self.name}: list each image once for each shape.")
        if any(video.asset_type != "YOUTUBE_VIDEO" for video in self.videos):
            raise ValueError(f"{self.name}: videos must be YouTube video assets.")
        if len({video.asset_id for video in self.videos}) != len(self.videos):
            raise ValueError(f"{self.name}: list each video once.")
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
        """The group, its filter, and at most an asset and a link for each text, plus the rest."""
        texts = len(self.headlines) + len(self.long_headlines) + len(self.descriptions)
        return 2 + 2 * texts + len(self.images) + len(self.videos) + len(self.search_themes)


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
    for field_type, noun in _NOUNS.items():
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
