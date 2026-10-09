# apps/api/integrations/meta_ads/creative_features.py

"""Every automatic change Meta can make to an ad, and how each is sent off or on.

Meta switches many of these on unless a creative says otherwise, so every creative
sends every entry. Offered entries can be turned on from the approval card; the rest
are always off, because they need data this tool doesn't collect or Meta doesn't
describe them well enough to offer. No live account has confirmed which keys Meta
accepts, so this list holds only keys Meta's reference documents.
"""

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any, Literal

type MetaAdsAdFormat = Literal["image", "video", "carousel"]
type MetaAdsChangeGroup = Literal["media", "text", "added"]

_ALL: frozenset[MetaAdsAdFormat] = frozenset({"image", "video", "carousel"})
_IMAGE: frozenset[MetaAdsAdFormat] = frozenset({"image"})
_VIDEO: frozenset[MetaAdsAdFormat] = frozenset({"video"})
_CAROUSEL: frozenset[MetaAdsAdFormat] = frozenset({"carousel"})
_LINK_ADS: frozenset[MetaAdsAdFormat] = frozenset({"image", "carousel"})


@dataclass(frozen=True, slots=True)
class MetaAdsAutomaticChange:
    """One automatic change; `feature` is its `creative_features_spec` key, if it has one."""

    key: str
    label: str
    description: str
    group: MetaAdsChangeGroup
    formats: frozenset[MetaAdsAdFormat]
    offered: bool
    ai_generated: bool = False
    feature: str | None = None


def _feature(
    key: str,
    label: str,
    description: str,
    group: MetaAdsChangeGroup,
    formats: frozenset[MetaAdsAdFormat],
    *,
    offered: bool = True,
    ai_generated: bool = False,
) -> MetaAdsAutomaticChange:
    return MetaAdsAutomaticChange(
        key, label, description, group, formats, offered, ai_generated, feature=key
    )


AUTOMATIC_CHANGES: tuple[MetaAdsAutomaticChange, ...] = (
    _feature(
        "adapt_to_placement",
        "Adapt to placement",
        "Shows the image taller or wider to fill each placement.",
        "media",
        _IMAGE,
    ),
    _feature(
        "image_touchups",
        "Visual touch-ups",
        "Crops and expands images to fit more placements.",
        "media",
        _IMAGE,
    ),
    _feature(
        "image_brightness_and_contrast",
        "Brightness and contrast",
        "Adjusts the brightness and contrast of images.",
        "media",
        _IMAGE,
    ),
    _feature(
        "image_uncrop",
        "Expand image",
        "Generates extra image around the edges to fit more placements.",
        "media",
        _IMAGE,
        ai_generated=True,
    ),
    _feature(
        "image_animation",
        "Image animation",
        "Turns a still image into a short animation.",
        "media",
        _IMAGE,
        ai_generated=True,
    ),
    _feature(
        "image_templates",
        "Add overlays",
        "Adds text and graphics on top of the image.",
        "added",
        _IMAGE,
        ai_generated=True,
    ),
    _feature(
        "video_auto_crop",
        "Video touch-ups",
        "Crops videos to fit more placements.",
        "media",
        _VIDEO,
    ),
    _feature(
        "video_filtering",
        "Video effects",
        "Adjusts the colour and brightness of videos.",
        "media",
        _VIDEO,
    ),
    _feature(
        "video_uncrop",
        "Expand video",
        "Generates extra video around the edges to fit more placements.",
        "media",
        _VIDEO,
        ai_generated=True,
    ),
    _feature(
        "text_optimizations",
        "Text improvements",
        "Swaps your primary text, headline, and description between positions, and "
        "highlights phrases from them.",
        "text",
        _ALL,
    ),
    _feature(
        "text_generation",
        "Text generation",
        "Writes extra versions of your primary text.",
        "text",
        _LINK_ADS,
        ai_generated=True,
    ),
    _feature(
        "text_translation",
        "Translate text",
        "Translates your text for people who speak other languages.",
        "text",
        _ALL,
    ),
    _feature(
        "image_text_translation",
        "Translate image text",
        "Translates text that appears in the image.",
        "text",
        _IMAGE,
    ),
    _feature(
        "translate_voiceover",
        "Translate voiceover",
        "Dubs English speech into Spanish.",
        "text",
        _VIDEO,
        ai_generated=True,
    ),
    _feature(
        "enhance_cta",
        "Enhance button",
        "Adds phrases from your text next to the button.",
        "text",
        _ALL,
    ),
    _feature(
        "description_automation",
        "Dynamic description",
        "Replaces carousel card descriptions with details Meta chooses.",
        "text",
        _CAROUSEL,
    ),
    _feature(
        "inline_comment",
        "Relevant comments",
        "Shows a relevant comment under the ad.",
        "added",
        frozenset({"image", "video"}),
    ),
    _feature(
        "creative_stickers",
        "Sticker button",
        "Adds a generated sticker that links to your website.",
        "added",
        frozenset({"image", "video"}),
        ai_generated=True,
    ),
    _feature(
        "reveal_details_over_time",
        "Reveal details over time",
        "Adds details from your website or app store page as people watch.",
        "added",
        _ALL,
    ),
    MetaAdsAutomaticChange(
        "multi_advertiser_ads",
        "Multi-advertiser ads",
        "Shows your ad next to ads from other businesses.",
        "added",
        _ALL,
        offered=True,
    ),
    MetaAdsAutomaticChange(
        "music",
        "Add music",
        "Adds background music Meta chooses.",
        "added",
        _LINK_ADS,
        offered=True,
    ),
    MetaAdsAutomaticChange(
        "carousel_reordering",
        "Reorder carousel cards",
        "Changes the order of cards to show the best performing first, on Facebook.",
        "media",
        _CAROUSEL,
        offered=True,
    ),
    MetaAdsAutomaticChange(
        "carousel_end_card",
        "Carousel end card",
        "Adds a final card with your Page's picture, on Facebook.",
        "added",
        _CAROUSEL,
        offered=True,
    ),
    # Catalogue features and those that need data this tool doesn't collect.
    _feature("add_text_overlay", "Catalogue overlays", "", "added", _ALL, offered=False),
    _feature("image_background_gen", "Generated backgrounds", "", "media", _ALL, offered=False),
    _feature("media_type_automation", "Product video", "", "media", _ALL, offered=False),
    _feature("dynamic_partner_content", "Partner content", "", "added", _ALL, offered=False),
    _feature("product_extensions", "Catalogue items", "", "added", _ALL, offered=False),
    _feature("site_extensions", "Site links", "", "added", _ALL, offered=False),
    _feature("pac_relaxation", "Flexible media", "", "media", _ALL, offered=False),
    # Keys Meta's create reference names without describing what they do.
    _feature("ig_video_native_subtitle", "Instagram subtitles", "", "text", _ALL, offered=False),
    _feature("product_browsing", "Product browsing", "", "added", _ALL, offered=False),
    _feature("product_metadata_automation", "Product details", "", "text", _ALL, offered=False),
    _feature("profile_card", "Profile card", "", "added", _ALL, offered=False),
    _feature(
        "standard_enhancements_catalog", "Catalogue enhancements", "", "media", _ALL, offered=False
    ),
    _feature("text_overlay_translation", "Overlay translation", "", "text", _ALL, offered=False),
)

AUTOMATIC_CHANGES_BY_KEY: Mapping[str, MetaAdsAutomaticChange] = {
    change.key: change for change in AUTOMATIC_CHANGES
}
OFFERED_CHANGE_KEYS: tuple[str, ...] = tuple(
    change.key for change in AUTOMATIC_CHANGES if change.offered
)


def offered_catalogue() -> list[dict[str, Any]]:
    """Describes the offered changes for the approval card."""
    return [
        {
            "key": change.key,
            "label": change.label,
            "description": change.description,
            "group": change.group,
            "ai_generated": change.ai_generated,
            "formats": sorted(change.formats),
        }
        for change in AUTOMATIC_CHANGES
        if change.offered
    ]


def has_ai_generated(enabled: Iterable[str]) -> bool:
    """Returns whether any enabled change has Meta generate its output with AI."""
    wanted = set(enabled)
    return any(change.ai_generated and change.key in wanted for change in AUTOMATIC_CHANGES)


def enabled_for(ad_format: MetaAdsAdFormat, enabled: Iterable[str]) -> frozenset[str]:
    """Returns the enabled changes that apply to this format; the rest are sent off."""
    wanted = set(enabled)
    return frozenset(
        change.key
        for change in AUTOMATIC_CHANGES
        if change.offered and change.key in wanted and ad_format in change.formats
    )


def features_spec(enabled: frozenset[str]) -> dict[str, dict[str, str]]:
    """Builds `creative_features_spec` with every catalogue feature, on only when enabled."""
    return {
        change.feature: {"enroll_status": "OPT_IN" if change.key in enabled else "OPT_OUT"}
        for change in AUTOMATIC_CHANGES
        if change.feature is not None
    }


def applied_changes(creative: Mapping[str, Any]) -> frozenset[str]:
    """Reads which catalogue changes a created creative has on, from Meta's read-back.

    Only what Meta reports as on counts; a value Meta doesn't return is not assumed on.
    """
    applied: set[str] = set()
    dof = creative.get("degrees_of_freedom_spec")
    features = dof.get("creative_features_spec") if isinstance(dof, Mapping) else None
    if isinstance(features, Mapping):
        for change in AUTOMATIC_CHANGES:
            detail = features.get(change.feature) if change.feature else None
            if isinstance(detail, Mapping) and detail.get("enroll_status") == "OPT_IN":
                applied.add(change.key)
    multi = creative.get("contextual_multi_ads")
    if isinstance(multi, Mapping) and multi.get("enroll_status") == "OPT_IN":
        applied.add("multi_advertiser_ads")
    feed = creative.get("asset_feed_spec")
    audios = feed.get("audios") if isinstance(feed, Mapping) else None
    if isinstance(audios, list) and any(
        isinstance(audio, Mapping) and str(audio.get("type", "")).upper() != "OPTED_OUT"
        for audio in audios
    ):
        applied.add("music")
    story = creative.get("object_story_spec")
    link_data = story.get("link_data") if isinstance(story, Mapping) else None
    if isinstance(link_data, Mapping) and link_data.get("child_attachments"):
        if link_data.get("multi_share_optimized") is True:
            applied.add("carousel_reordering")
        if link_data.get("multi_share_end_card") is True:
            applied.add("carousel_end_card")
    return frozenset(applied)


def change_labels(keys: Iterable[str]) -> list[str]:
    """Returns plain labels in catalogue order."""
    wanted = set(keys)
    return [change.label for change in AUTOMATIC_CHANGES if change.key in wanted]
