# apps/api/integrations/meta_ads/tools/schemas/ads.py

"""Input and result contracts for creating ads in existing Meta ad sets."""

import re
from collections import Counter
from collections.abc import Mapping, Sequence
from typing import Annotated, Any, Literal, Protocol, Self
from urllib.parse import urlsplit

from pydantic import AfterValidator, Field, model_validator

from services.integrations.context.results import IntegrationFanOutEntry, IntegrationFanOutOutput
from services.integrations.files import FileReference

from ...creative_features import OFFERED_CHANGE_KEYS, MetaAdsAdFormat
from ...models import MetaAdsId, MetaAdsStrictModel, MetaAdsText
from ...references import (
    MetaAdsAdSetReference,
    MetaAdsInstagramAccountReference,
    MetaAdsMediaReference,
    MetaAdsPageReference,
    MetaAdsPostReference,
)
from .media import MetaAdsMediaUpload
from .objects import MetaAdsReviewState

MAX_ADS = 50
MAX_AD_SETS = 10
MAX_FILES = 20
MAX_NAME_LENGTH = 200
# Buttons for website and other goals, and for app goals; Meta's dry run is the final check.
WEBSITE_BUTTONS = (
    "LEARN_MORE",
    "SHOP_NOW",
    "SIGN_UP",
    "BOOK_NOW",
    "CONTACT_US",
    "DOWNLOAD",
    "GET_OFFER",
    "GET_QUOTE",
    "SUBSCRIBE",
    "APPLY_NOW",
    "ORDER_NOW",
    "BUY_NOW",
    "WATCH_MORE",
    "NO_BUTTON",
)
APP_BUTTONS = ("INSTALL_MOBILE_APP", "USE_APP", "DOWNLOAD")
ALL_BUTTONS = tuple(dict.fromkeys((*WEBSITE_BUTTONS, *APP_BUTTONS)))
DEFAULT_BUTTON = "LEARN_MORE"
# Shared settings an ad can override, with the value each takes when the call leaves it out.
_SHARED_DEFAULTS: dict[str, str | None] = {
    "link": None,
    "call_to_action": DEFAULT_BUTTON,
    "url_tags": None,
    "status": "paused",
}
_MAX_HASHTAGS = 30
# What an existing post fixes, because the post is the creative.
_FIXED_BY_POST = (
    "primary_text",
    "headline",
    "description",
    "media",
    "vertical_media",
    "thumbnail",
    "cards",
    "disclaimer",
    "url_tags",
)
UPLOAD_VIDEOS_FIRST = (
    "Upload videos with meta_ads_upload_media first, then use the media reference it returns."
)


def _https_link(value: str) -> str:
    """Accepts an absolute https address with a host and no credentials or spaces."""
    try:
        parts = urlsplit(value)
    except ValueError:
        raise ValueError("Use a full https:// web address.") from None
    if (
        parts.scheme != "https"
        or not parts.hostname
        or parts.username is not None
        or parts.password is not None
        or any(char.isspace() or ord(char) < 32 for char in value)
    ):
        raise ValueError("Use a full https:// web address without a username or password.")
    return value


def _url_tags(value: str) -> str:
    if not value.isascii() or not re.fullmatch(r"[^=&\s]+=[^&\s]*(?:&[^=&\s]+=[^&\s]*)*", value):
        raise ValueError(
            "Write URL tags as key=value pairs joined by &, for example utm_source=meta."
        )
    return value


def _ad_text(value: str) -> str:
    if not value.strip():
        raise ValueError("Write some text.")
    return value


def _primary_text(value: str) -> str:
    if len(re.findall(r"(?<![\w#])#\w", value)) > _MAX_HASHTAGS:
        raise ValueError(f"Instagram allows at most {_MAX_HASHTAGS} hashtags.")
    return _ad_text(value)


type MetaAdsLink = Annotated[
    str,
    Field(max_length=1000, description="https:// web address people go to."),
    AfterValidator(_https_link),
]
type MetaAdsUrlTags = Annotated[
    str,
    Field(
        max_length=512,
        description="Tracking parameters added to the link, such as utm_source=meta.",
    ),
    AfterValidator(_url_tags),
]
type MetaAdsButton = Literal[ALL_BUTTONS]
type MetaAdsAdStatusChoice = Literal["paused", "active"]
type MetaAdsAutomaticChangeKey = Literal[OFFERED_CHANGE_KEYS]
type MetaAdsMediaInput = Annotated[
    MetaAdsMediaReference | FileReference, Field(discriminator="entity_kind")
]
type MetaAdsHeadline = Annotated[str, Field(max_length=255), AfterValidator(_ad_text)]
type MetaAdsDescription = Annotated[str, Field(max_length=255), AfterValidator(_ad_text)]


class MetaAdsCarouselCard(MetaAdsStrictModel):
    media: MetaAdsMediaInput = Field(description="Image, or ready video, for this card.")
    thumbnail: MetaAdsMediaInput | None = Field(
        default=None, description="Image shown before a video card plays."
    )
    headline: MetaAdsHeadline
    description: MetaAdsDescription | None = None
    link: MetaAdsLink | None = Field(default=None, description="Defaults to the ad's link.")
    call_to_action: MetaAdsButton | None = Field(
        default=None, description="Defaults to the ad's button."
    )

    @model_validator(mode="after")
    def _check_media(self) -> Self:
        if self.thumbnail is not None and (
            media_kind(self.media) != "video" or media_kind(self.thumbnail) != "image"
        ):
            raise ValueError("Only video cards take a thumbnail, and it must be an image.")
        return self


class MetaAdsDisclaimer(MetaAdsStrictModel):
    type: Literal["terms_and_conditions", "offer_details", "disclaimer"]
    text: Annotated[str, Field(max_length=500), AfterValidator(_ad_text)]
    url: MetaAdsLink | None = None


class MetaAdsAdContent(MetaAdsStrictModel):
    """One ad's creative and settings; where it goes is set by the call that holds it."""

    name: Annotated[str, Field(max_length=MAX_NAME_LENGTH), AfterValidator(_ad_text)]
    format: MetaAdsAdFormat
    primary_text: Annotated[str, Field(max_length=2200), AfterValidator(_primary_text)] | None = (
        Field(default=None, description="Required for every format but existing_post.")
    )
    post: MetaAdsPostReference | None = Field(
        default=None, description="For existing_post: the post from meta_ads_list_assets."
    )
    headline: MetaAdsHeadline | None = Field(
        default=None, description="Required for image and video ads."
    )
    description: MetaAdsDescription | None = Field(
        default=None, description="For image and video ads; carousel cards take their own."
    )
    media: MetaAdsMediaInput | None = Field(
        default=None, description="Image or ready video, for image and video ads."
    )
    vertical_media: MetaAdsMediaInput | None = Field(
        default=None, description="9:16 version of the same format shown in Stories and Reels."
    )
    thumbnail: MetaAdsMediaInput | None = Field(
        default=None, description="Image shown before a video ad plays."
    )
    cards: list[MetaAdsCarouselCard] | None = Field(default=None, min_length=2, max_length=10)
    link: MetaAdsLink | None = Field(
        default=None, description="Only when this ad's link differs from the shared one."
    )
    call_to_action: MetaAdsButton | None = Field(
        default=None, description="Only when this ad's button differs from the shared one."
    )
    url_tags: MetaAdsUrlTags | None = Field(
        default=None, description="Only when this ad's URL tags differ from the shared ones."
    )
    status: MetaAdsAdStatusChoice | None = Field(
        default=None, description="Only when this ad's status differs from the shared one."
    )
    disclaimer: MetaAdsDisclaimer | None = None

    @model_validator(mode="after")
    def _fits_format(self) -> Self:
        if self.format == "existing_post":
            return self._fits_post()
        if self.post is not None:
            raise ValueError("Only existing_post ads take a post.")
        if self.primary_text is None:
            raise ValueError("Write the primary text.")
        if self.format == "carousel":
            if self.cards is None or self.media or self.vertical_media or self.thumbnail:
                raise ValueError(
                    "Carousel ads take cards, not media, vertical_media, or thumbnail."
                )
            if self.headline is not None or self.description is not None:
                raise ValueError(
                    "Carousel ads take a headline and description on each card instead."
                )
            media = [media_key(card.media) for card in self.cards]
            if len(set(media)) != len(media):
                raise ValueError("Use different media on each carousel card.")
            return self
        if self.cards is not None or self.media is None:
            raise ValueError("Image and video ads take media, not cards.")
        if self.headline is None:
            raise ValueError("Image and video ads need a headline.")
        for item in (self.media, self.vertical_media):
            if self.format == "video" and isinstance(item, FileReference):
                raise ValueError(UPLOAD_VIDEOS_FIRST)
            if item is not None and media_kind(item) != self.format:
                raise ValueError(f"Use {self.format} media for {self.format} ads.")
        if self.thumbnail is not None and (
            self.format != "video" or media_kind(self.thumbnail) != "image"
        ):
            raise ValueError("Only video ads take a thumbnail, and it must be an image.")
        return self

    def _fits_post(self) -> Self:
        if self.post is None:
            raise ValueError("Existing post ads need a post from meta_ads_list_assets.")
        if fixed := [name for name in _FIXED_BY_POST if getattr(self, name) is not None]:
            raise ValueError(
                f"An existing post runs as it is, so leave out {', '.join(fixed)}. To change "
                "its text or media, create an image, video, or carousel ad instead."
            )
        if self.post.source == "facebook" and (self.link or self.call_to_action):
            raise ValueError(
                "A Facebook post keeps its own link and button; only Instagram posts take "
                "link and call_to_action."
            )
        return self


class MetaAdsAdDesign(MetaAdsAdContent):
    """One ad design, created once in each of its ad sets."""

    ad_sets: list[MetaAdsAdSetReference] = Field(min_length=1, max_length=MAX_AD_SETS)


class MetaAdsCreateAdsRequest(MetaAdsStrictModel):
    """Every argument of an ad creation call; shared values apply unless an ad overrides them."""

    ads: list[MetaAdsAdDesign] = Field(min_length=1, max_length=MAX_ADS)
    page: MetaAdsPageReference
    instagram_account: MetaAdsInstagramAccountReference | None = None
    link: MetaAdsLink | None = None
    call_to_action: MetaAdsButton | None = None
    url_tags: MetaAdsUrlTags | None = None
    status: MetaAdsAdStatusChoice = "paused"
    automatic_changes: list[MetaAdsAutomaticChangeKey] | None = Field(
        default=None, max_length=len(OFFERED_CHANGE_KEYS)
    )

    @model_validator(mode="after")
    def _check_call(self) -> Self:
        accounts = {ad_set.account_id for design in self.ads for ad_set in design.ad_sets}
        check_ads(
            self,
            [[ad_set.adset_id for ad_set in design.ad_sets] for design in self.ads],
            accounts=accounts,
        )
        return self

    @property
    def account_id(self) -> str:
        return self.page.account_id

    @property
    def instagram_user_id(self) -> str | None:
        return self.instagram_account.instagram_user_id if self.instagram_account else None


class SharedAdSettings(Protocol):
    """The settings every ad in a call shares unless it sets its own."""

    @property
    def ads(self) -> Sequence[MetaAdsAdContent]: ...
    @property
    def page(self) -> MetaAdsPageReference: ...
    @property
    def instagram_account(self) -> MetaAdsInstagramAccountReference | None: ...
    @property
    def link(self) -> str | None: ...
    @property
    def call_to_action(self) -> str | None: ...
    @property
    def url_tags(self) -> str | None: ...
    @property
    def automatic_changes(self) -> Sequence[str] | None: ...


def check_ads(
    request: SharedAdSettings, ad_sets: Sequence[Sequence[str]], *, accounts: set[str]
) -> None:
    """Checks a call's ads against the per-call limits, given each ad's ad sets in order.

    Raises:
        ValueError: The ads use more than one ad account, or go over a limit.
    """
    changes = request.automatic_changes or ()
    if len(set(changes)) != len(changes):
        raise ValueError("Name each automatic change once.")
    accounts = {*accounts, request.page.account_id}
    if request.instagram_account is not None:
        accounts.add(request.instagram_account.account_id)
    files: set[str] = set()
    for design, ids in zip(request.ads, ad_sets, strict=True):
        if len(set(ids)) != len(ids):
            raise ValueError("Choose each ad set once per ad.")
        if design.post is not None:
            accounts.add(design.post.account_id)
        for item in design_media(design):
            if isinstance(item, FileReference):
                files.add(str(item.entity_id))
            else:
                accounts.add(item.account_id)
    if len(accounts) != 1:
        raise ValueError("Use one ad account for the Page, ad sets, media, and posts.")
    if sum(len(ids) for ids in ad_sets) > MAX_ADS:
        raise ValueError(f"Create at most {MAX_ADS} ads, counting each ad set an ad goes in.")
    if len({item for ids in ad_sets for item in ids}) > MAX_AD_SETS:
        raise ValueError(f"Use at most {MAX_AD_SETS} ad sets in one call.")
    if len(files) > MAX_FILES:
        raise ValueError(f"Use at most {MAX_FILES} workspace Files in one call.")
    names = Counter(design.name.strip().casefold() for design in request.ads)
    if any(count > 1 for count in names.values()):
        raise ValueError("Give each ad a different name.")


def follow_shared(values: Mapping[str, Any]) -> list[Any]:
    """Drops each ad's copies of the shared settings, so the ad follows later shared changes."""
    shared = {key: values.get(key) or default for key, default in _SHARED_DEFAULTS.items()}
    ads = values.get("ads")
    return [
        {
            key: value
            for key, value in ad.items()
            if key not in shared or value is None or value != shared[key]
        }
        if isinstance(ad, Mapping)
        else ad
        for ad in (ads if isinstance(ads, list) else ())
    ]


def design_media(design: MetaAdsAdContent) -> list[MetaAdsMediaReference | FileReference]:
    """Lists every media input of a design, cards included, in order."""
    items = [design.media, design.vertical_media, design.thumbnail]
    for card in design.cards or ():
        items.extend((card.media, card.thumbnail))
    return [item for item in items if item is not None]


def media_kind(item: MetaAdsMediaReference | FileReference) -> str:
    """Returns the media type; Files can only be images, which preparation checks."""
    return item.media_type if isinstance(item, MetaAdsMediaReference) else "image"


type MediaKey = tuple[str, str]


def media_key(item: MetaAdsMediaReference | FileReference) -> MediaKey:
    """Identifies a media input across the call: a File, an image hash, or a video ID."""
    if isinstance(item, FileReference):
        return ("file", str(item.entity_id))
    return (item.media_type, item.provider_entity_id)


type MetaAdsCreatedAdOutcome = Literal["created", "failed", "unverified"]


class MetaAdsCreatedAd(MetaAdsStrictModel):
    design_index: int = Field(ge=0, lt=MAX_ADS)
    name: MetaAdsText
    adset_id: MetaAdsId
    adset_name: MetaAdsText | None
    format: MetaAdsAdFormat
    requested_status: MetaAdsAdStatusChoice
    outcome: MetaAdsCreatedAdOutcome
    # True when an unclear reply was settled by finding the new ad by name.
    recovered: bool
    # False when the ad couldn't be read back after it was created.
    verified: bool
    ad_id: MetaAdsId | None
    creative_id: MetaAdsId | None
    effective_status: MetaAdsText | None
    review: MetaAdsReviewState
    review_reasons: list[MetaAdsText] = Field(max_length=5)
    # Automatic changes Meta shows on that the approval left off.
    unexpected_changes: list[MetaAdsText] = Field(max_length=40)
    preview_url: str | None = Field(default=None, max_length=2048)
    error_code: str | None = Field(default=None, max_length=100)
    message: str | None = Field(default=None, max_length=1000)


class MetaAdsCreateAdsData(MetaAdsStrictModel):
    account_id: MetaAdsId
    ads: list[MetaAdsCreatedAd] = Field(max_length=MAX_ADS)
    # Workspace Files uploaded to the media library for these ads.
    uploads: list[MetaAdsMediaUpload] = Field(max_length=MAX_FILES)
    automatic_changes: list[MetaAdsAutomaticChangeKey]
    # True when an AI-generated change made every ad start off.
    created_off_for_ai: bool


class MetaAdsCreateAdsEntry(IntegrationFanOutEntry):
    data: MetaAdsCreateAdsData | None = None


class MetaAdsCreateAdsOutput(IntegrationFanOutOutput):
    results: list[MetaAdsCreateAdsEntry]
