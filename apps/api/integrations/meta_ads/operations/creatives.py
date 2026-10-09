# apps/api/integrations/meta_ads/operations/creatives.py

"""Maps one ad's design to Meta's creative spec, with every automatic change explicit.

Values marked unverified here come from Meta's reference documents and no live
account has confirmed them.
"""

from dataclasses import dataclass
from typing import Any, Literal
from urllib.parse import urlsplit

from ..creative_features import MetaAdsAdFormat, features_spec

# Meta fills a missing description from the landing page; its asset feed guide sends a
# space to leave one blank. Unverified for link and video data.
EMPTY_DESCRIPTION = " "
# Every format Meta's format automation can turn an ad into, each with no sources.
_TRANSFORMED_FORMATS = (
    "single_media",
    "carousel",
    "da_collection",
    "sa_collection",
    "video_slideshow",
)
# Stories and Reels show the vertical version; every other placement shows the main one.
# Rules are tried in priority order, so the broad main rule only covers what remains.
_VERTICAL_PLACEMENTS = {
    "publisher_platforms": ["facebook", "instagram"],
    "facebook_positions": ["story", "facebook_reels"],
    "instagram_positions": ["story", "reels"],
}
_MAIN_PLACEMENTS = {
    "publisher_platforms": ["facebook", "instagram", "audience_network", "messenger", "threads"]
}
_DISCLAIMER_TITLES = {
    "terms_and_conditions": "TERMS_AND_CONDITIONS",
    "offer_details": "OFFER_DETAILS",
    "disclaimer": "DISCLAIMER",
}
# Second-level labels that sit under a country code, as in example.co.uk.
_COUNTRY_SECOND_LEVELS = frozenset({"ac", "co", "com", "edu", "gov", "net", "org"})


@dataclass(frozen=True, slots=True)
class CreativeImage:
    image_hash: str


@dataclass(frozen=True, slots=True)
class CreativeVideo:
    video_id: str
    thumbnail_hash: str | None = None
    thumbnail_url: str | None = None

    def __post_init__(self) -> None:
        if self.thumbnail_hash is not None and self.thumbnail_url is not None:
            raise ValueError("Meta Ads videos take one thumbnail")

    def thumbnail(self, *, hash_key: str, url_key: str) -> dict[str, str]:
        """Returns the thumbnail under Meta's key for a hash or an address; Instagram requires one."""
        if self.thumbnail_hash:
            return {hash_key: self.thumbnail_hash}
        if self.thumbnail_url:
            return {url_key: self.thumbnail_url}
        raise ValueError("Meta Ads videos need a thumbnail")


type CreativeMedia = CreativeImage | CreativeVideo


@dataclass(frozen=True, slots=True)
class CreativeCard:
    media: CreativeMedia
    headline: str
    description: str | None
    link: str
    call_to_action: str


@dataclass(frozen=True, slots=True)
class CreativeDisclaimer:
    type: Literal["terms_and_conditions", "offer_details", "disclaimer"]
    text: str
    url: str | None


@dataclass(frozen=True, slots=True)
class CreativeInput:
    """Everything one creative needs, with shared values and overrides already applied."""

    format: MetaAdsAdFormat
    page_id: str
    instagram_user_id: str | None
    primary_text: str
    headline: str | None
    description: str | None
    link: str
    call_to_action: str
    url_tags: str | None
    media: CreativeMedia | None
    vertical: CreativeMedia | None
    cards: tuple[CreativeCard, ...]
    enabled: frozenset[str]
    disclaimer: CreativeDisclaimer | None = None


def creative_spec(item: CreativeInput) -> dict[str, Any]:
    """Builds the inline creative for `POST /act_{id}/ads`."""
    story: dict[str, Any] = {"page_id": item.page_id}
    if item.instagram_user_id:
        story["instagram_user_id"] = item.instagram_user_id
    spec: dict[str, Any] = {"object_story_spec": story, **_automatic_change_values(item)}
    if item.vertical is not None:
        spec["asset_feed_spec"] = {**spec.get("asset_feed_spec", {}), **_placement_feed(item)}
    elif item.format == "video":
        story["video_data"] = _video_data(item)
    else:
        story["link_data"] = _link_data(item)
    if item.url_tags:
        spec["url_tags"] = item.url_tags
    if item.disclaimer is not None:
        disclaimer = {
            "title": _DISCLAIMER_TITLES[item.disclaimer.type],
            "text": item.disclaimer.text,
        }
        if item.disclaimer.url:
            disclaimer["url"] = item.disclaimer.url
        spec["ad_disclaimer_spec"] = disclaimer
    return spec


def _automatic_change_values(item: CreativeInput) -> dict[str, Any]:
    """Sends every automatic change, off unless the operator turned it on for this format."""
    enabled = item.enabled
    values: dict[str, Any] = {
        "degrees_of_freedom_spec": {"creative_features_spec": features_spec(enabled)},
        "contextual_multi_ads": {
            "enroll_status": "OPT_IN" if "multi_advertiser_ads" in enabled else "OPT_OUT"
        },
        # From v26 Meta may send clicks to a shop instead of the website.
        "destination_spec": {"destination_type": "WEBSITE_AND_SHOP_OPT_OUT"},
        "format_transformation_spec": [
            {"format": name, "data_source": ["none"]} for name in _TRANSFORMED_FORMATS
        ],
    }
    if item.format in ("image", "carousel"):
        values["interactive_components_spec"] = {
            "components": [{"type": "product_tag", "enroll_status": "opt_out"}]
        }
        values["asset_feed_spec"] = {
            "audios": [{"type": "RANDOM" if "music" in enabled else "OPTED_OUT"}]
        }
    if item.format == "carousel":
        values["portrait_customizations"] = {"carousel_delivery_mode": "fixed_num_cards"}
    return values


def _call_to_action(button: str, link: str) -> dict[str, Any]:
    return {"type": button, "value": {"link": link}}


def _link_data(item: CreativeInput) -> dict[str, Any]:
    data: dict[str, Any] = {
        "link": item.link,
        "message": item.primary_text,
        "call_to_action": _call_to_action(item.call_to_action, item.link),
    }
    if item.format == "carousel":
        data["child_attachments"] = [_card(card) for card in item.cards]
        data["multi_share_optimized"] = "carousel_reordering" in item.enabled
        data["multi_share_end_card"] = "carousel_end_card" in item.enabled
        return data
    if not isinstance(item.media, CreativeImage):
        raise TypeError("Meta Ads image ads need an image")
    data["image_hash"] = item.media.image_hash
    data["name"] = item.headline
    data["description"] = item.description or EMPTY_DESCRIPTION
    # Shows each image at its own shape rather than cropping it to 1.91:1.
    data["use_flexible_image_aspect_ratio"] = True
    return data


def _card(card: CreativeCard) -> dict[str, Any]:
    data: dict[str, Any] = {
        "link": card.link,
        "name": card.headline,
        "description": card.description or EMPTY_DESCRIPTION,
        "call_to_action": _call_to_action(card.call_to_action, card.link),
    }
    if isinstance(card.media, CreativeImage):
        data["image_hash"] = card.media.image_hash
    else:
        data["video_id"] = card.media.video_id
        data.update(card.media.thumbnail(hash_key="image_hash", url_key="picture"))
    return data


def _video_data(item: CreativeInput) -> dict[str, Any]:
    if not isinstance(item.media, CreativeVideo):
        raise TypeError("Meta Ads video ads need a video")
    return {
        "video_id": item.media.video_id,
        "message": item.primary_text,
        "title": item.headline,
        "link_description": item.description or EMPTY_DESCRIPTION,
        "call_to_action": _call_to_action(item.call_to_action, item.link),
        **item.media.thumbnail(hash_key="image_hash", url_key="image_url"),
    }


def _placement_feed(item: CreativeInput) -> dict[str, Any]:
    """Builds placement customisation: the vertical version in Stories and Reels only."""
    if item.media is None or item.vertical is None:
        raise ValueError("Meta Ads placement customisation needs two versions")
    text_automation = "OPT_IN" if "text_optimizations" in item.enabled else "OPT_OUT"
    label = "image_label" if item.format == "image" else "video_label"
    feed: dict[str, Any] = {
        "bodies": [{"text": item.primary_text, "automation_status": text_automation}],
        "titles": [{"text": item.headline, "automation_status": text_automation}],
        "descriptions": [
            {"text": item.description or EMPTY_DESCRIPTION, "automation_status": text_automation}
        ],
        "link_urls": [{"website_url": item.link}],
        "call_to_action_types": [item.call_to_action],
        "ad_formats": ["SINGLE_IMAGE" if item.format == "image" else "SINGLE_VIDEO"],
        "optimization_type": "PLACEMENT",
        "asset_customization_rules": [
            {
                "customization_spec": _VERTICAL_PLACEMENTS,
                label: {"name": "vertical"},
                "priority": 1,
            },
            {"customization_spec": _MAIN_PLACEMENTS, label: {"name": "main"}, "priority": 2},
        ],
    }
    assets = [_feed_asset(item.media, "main"), _feed_asset(item.vertical, "vertical")]
    feed["images" if item.format == "image" else "videos"] = assets
    return feed


def _feed_asset(media: CreativeMedia, name: str) -> dict[str, Any]:
    labels = [{"name": name}]
    if isinstance(media, CreativeImage):
        return {"hash": media.image_hash, "adlabels": labels}
    thumbnail = media.thumbnail(hash_key="thumbnail_hash", url_key="thumbnail_url")
    return {"video_id": media.video_id, **thumbnail, "adlabels": labels}


def conversion_domain(link: str) -> str:
    """Approximates the registrable domain Meta wants, such as example.co.uk for shop.example.co.uk.

    There's no public suffix list here, so a country code with a common second level
    keeps three labels and anything else keeps two. Meta's dry run checks the result.
    """
    host = (urlsplit(link).hostname or "").rstrip(".").lower()
    labels = host.split(".")
    under_country_code = len(labels[-1]) == 2 and labels[-2] in _COUNTRY_SECOND_LEVELS
    keep = 3 if len(labels) > 2 and under_country_code else 2
    return ".".join(labels[-keep:])
