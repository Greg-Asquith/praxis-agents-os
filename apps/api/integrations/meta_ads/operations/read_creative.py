# apps/api/integrations/meta_ads/operations/read_creative.py

"""Reads an ad's live creative back into the ad model that ad creation builds from.

A shape the model can't express is refused with its reason rather than rebuilt without
it. Meta's read-back shape of these fields is unverified on a live account, so unknown
keys are refused too.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit

from ..client import MetaAdsClient
from ..creative_features import applied_changes
from ..tools.schemas.ads import MediaKey
from .create_objects import read_created
from .creatives import CreativeImage, CreativeMedia, CreativeVideo

CREATIVE_FIELDS = (
    "id,creative{id,object_story_spec,asset_feed_spec,degrees_of_freedom_spec,"
    "contextual_multi_ads,url_tags,object_story_id,source_instagram_media_id,"
    "instagram_user_id,object_id,destination_spec,applink_treatment,ad_disclaimer_spec,"
    "product_set_id,interactive_components_spec,portrait_customizations,"
    "facebook_branded_content,instagram_branded_content}"
)
_SHOP_DEFAULT = "WEBSITE_AND_SHOP_OPT_OUT"
_DISCLAIMER_TYPES = {
    "TERMS_AND_CONDITIONS": "terms_and_conditions",
    "OFFER_DETAILS": "offer_details",
    "DISCLAIMER": "disclaimer",
}
# Keys each part of a creative may hold; anything else would be lost in a rebuild.
_STORY_KEYS = frozenset({"page_id", "instagram_user_id", "link_data", "video_data"})
_LINK_KEYS = frozenset(
    {
        "link",
        "message",
        "name",
        "description",
        "caption",
        "image_hash",
        "picture",
        "call_to_action",
        "child_attachments",
        "multi_share_optimized",
        "multi_share_end_card",
        "use_flexible_image_aspect_ratio",
        "attachment_style",
    }
)
_VIDEO_KEYS = frozenset(
    {
        "video_id",
        "message",
        "title",
        "link_description",
        "call_to_action",
        "image_hash",
        "image_url",
    }
)
_CARD_KEYS = frozenset(
    {"link", "name", "description", "image_hash", "video_id", "picture", "call_to_action"}
)
_PLACEMENT_FEED_KEYS = frozenset(
    {
        "bodies",
        "titles",
        "descriptions",
        "link_urls",
        "call_to_action_types",
        "ad_formats",
        "optimization_type",
        "asset_customization_rules",
        "images",
        "videos",
        "audios",
    }
)


class UneditableCreativeError(Exception):
    """The live creative holds something this tool can't rebuild."""


@dataclass(frozen=True, slots=True)
class LiveCreative:
    """An ad's creative as it runs: its content in ad model form, and what a rebuild keeps."""

    creative_id: str
    # `MetaAdsAdContent` fields as JSON, without the name; media are library references.
    content: dict[str, Any]
    page_id: str
    instagram_user_id: str | None
    media: dict[MediaKey, CreativeMedia]
    # Every automatic change Meta shows on, offered on the card or not.
    enabled: frozenset[str]
    destination_type: str
    applink_treatment: str | None
    display_link: str | None
    # Placement versions live in an asset feed, which Meta won't turn back into one version.
    has_vertical: bool


async def read_live_creatives(
    client: MetaAdsClient, *, account_id: str, ad_ids: Sequence[str], operation: str
) -> dict[str, LiveCreative | str]:
    """Reads each ad's creative through the ad account; a creative that can't be edited gives its reason."""
    rows = await read_created(
        client,
        account_id=account_id,
        edge="ads",
        object_ids=ad_ids,
        fields=CREATIVE_FIELDS,
        operation=operation,
    )
    creatives: dict[str, LiveCreative | str] = {}
    for ad_id in ad_ids:
        creative = rows.get(ad_id, {}).get("creative")
        try:
            if not isinstance(creative, Mapping):
                raise UneditableCreativeError("This ad's creative couldn't be read.")
            creatives[ad_id] = live_creative(creative, account_id=account_id)
        except UneditableCreativeError as exc:
            creatives[ad_id] = str(exc)
    return creatives


def live_creative(creative: Mapping[str, Any], *, account_id: str) -> LiveCreative:
    """Maps one creative from Meta's read-back.

    Raises:
        UneditableCreativeError: The creative is a type this tool doesn't build.
    """
    _refuse_unsupported(creative)
    reader = _Reader(account_id)
    story = creative.get("object_story_spec")
    if isinstance(story, Mapping):
        content, page_id, has_vertical = reader.story(story, creative.get("asset_feed_spec"))
        instagram = story.get("instagram_user_id") or creative.get("instagram_user_id")
    else:
        content, page_id = reader.post(creative)
        instagram, has_vertical = creative.get("instagram_user_id"), False
    if url_tags := creative.get("url_tags"):
        content["url_tags"] = str(url_tags)
    if disclaimer := _disclaimer(creative.get("ad_disclaimer_spec")):
        content["disclaimer"] = disclaimer
    destination = creative.get("destination_spec")
    return LiveCreative(
        creative_id=str(creative.get("id") or ""),
        content=content,
        page_id=page_id,
        instagram_user_id=str(instagram) if instagram else None,
        media=reader.media,
        enabled=applied_changes(creative) | reader.enabled,
        destination_type=str(
            (destination.get("destination_type") if isinstance(destination, Mapping) else None)
            or _SHOP_DEFAULT
        ),
        applink_treatment=_text(creative.get("applink_treatment")),
        display_link=reader.display_link,
        has_vertical=has_vertical,
    )


def _refuse_unsupported(creative: Mapping[str, Any]) -> None:
    if creative.get("product_set_id"):
        raise UneditableCreativeError("This is a catalogue ad, which can't be edited here yet.")
    if creative.get("facebook_branded_content") or creative.get("instagram_branded_content"):
        raise UneditableCreativeError("This is a partnership ad, which can't be edited here.")
    components = creative.get("interactive_components_spec")
    if "poll" in str(components).lower():
        raise UneditableCreativeError(
            "Meta doesn't allow ads with a poll to change their creative."
        )


class _Reader:
    """Collects media and settings while mapping one creative's parts."""

    def __init__(self, account_id: str) -> None:
        self.account_id = account_id
        self.media: dict[MediaKey, CreativeMedia] = {}
        self.enabled: frozenset[str] = frozenset()
        self.display_link: str | None = None

    def story(self, story: Mapping[str, Any], feed: Any) -> tuple[dict[str, Any], str, bool]:
        _only(story, _STORY_KEYS, "This ad's creative")
        page_id = _text(story.get("page_id"))
        if page_id is None:
            raise UneditableCreativeError("This ad's creative doesn't name its Page.")
        if isinstance(feed, Mapping) and feed.get("optimization_type") == "PLACEMENT":
            return self.placement_feed(feed), page_id, True
        if isinstance(feed, Mapping) and set(feed) - {"audios"}:
            raise UneditableCreativeError(
                "This ad mixes several texts or media for Meta to choose from, which can't be "
                "edited here yet."
            )
        if isinstance(story.get("video_data"), Mapping):
            return self.video(story["video_data"]), page_id, False
        link_data = story.get("link_data")
        if not isinstance(link_data, Mapping):
            raise UneditableCreativeError("This ad's creative type can't be edited here.")
        _only(link_data, _LINK_KEYS, "This ad's creative")
        self.display_link = _text(link_data.get("caption"))
        if link_data.get("child_attachments"):
            return self.carousel(link_data), page_id, False
        return self.image(link_data), page_id, False

    def image(self, data: Mapping[str, Any]) -> dict[str, Any]:
        image_hash = _text(data.get("image_hash"))
        if image_hash is None:
            raise UneditableCreativeError("This ad's image isn't in the media library.")
        content = self.link_settings(data, data.get("link"))
        content.update(
            format="image",
            primary_text=_text(data.get("message")),
            headline=_text(data.get("name")),
            description=_text(data.get("description")),
            media=self.image_reference(image_hash),
        )
        return _present(content)

    def video(self, data: Mapping[str, Any]) -> dict[str, Any]:
        _only(data, _VIDEO_KEYS, "This ad's video")
        cta = data.get("call_to_action")
        link = cta.get("value", {}).get("link") if isinstance(cta, Mapping) else None
        content = self.link_settings(data, link)
        content.update(
            format="video",
            primary_text=_text(data.get("message")),
            headline=_text(data.get("title")),
            description=_text(data.get("link_description")),
            media=self.video_reference(data, "image_hash", "image_url"),
        )
        return _present(content)

    def carousel(self, data: Mapping[str, Any]) -> dict[str, Any]:
        content = self.link_settings(data, data.get("link"))
        cards = []
        for card in data["child_attachments"]:
            if not isinstance(card, Mapping):
                raise UneditableCreativeError("This carousel's cards couldn't be read.")
            _only(card, _CARD_KEYS, "A carousel card")
            if card.get("video_id"):
                media = self.video_reference(card, "image_hash", "picture")
            elif image_hash := _text(card.get("image_hash")):
                media = self.image_reference(image_hash)
            else:
                raise UneditableCreativeError("A carousel card's image isn't in the media library.")
            card_link, button = _call_to_action(card.get("call_to_action"), card.get("link"))
            cards.append(
                _present(
                    {
                        "media": media,
                        "headline": _text(card.get("name")),
                        "description": _text(card.get("description")),
                        "link": card_link if card_link != content.get("link") else None,
                        "call_to_action": button
                        if button != content.get("call_to_action")
                        else None,
                    }
                )
            )
        content.update(format="carousel", primary_text=_text(data.get("message")), cards=cards)
        return _present(content)

    def placement_feed(self, feed: Mapping[str, Any]) -> dict[str, Any]:
        """Reads the main and vertical versions Praxis builds for Stories and Reels."""
        _only(feed, _PLACEMENT_FEED_KEYS, "This ad's placement versions")
        texts = {key: feed.get(key) or [] for key in ("bodies", "titles", "descriptions")}
        if (
            any(len(items) != 1 for items in texts.values())
            or len(feed.get("link_urls") or []) != 1
        ):
            raise UneditableCreativeError(
                "This ad has several texts for Meta to choose from, which can't be edited here yet."
            )
        image = bool(feed.get("images"))
        assets = {
            _label(asset): asset for asset in (feed.get("images") or feed.get("videos") or [])
        }
        if set(assets) != {"main", "vertical"}:
            raise UneditableCreativeError(
                "This ad's placement versions were set up outside Praxis, so they can't be "
                "edited here."
            )
        version = self.image_feed_asset if image else self.video_feed_asset
        body, title, description = (texts[key][0] for key in ("bodies", "titles", "descriptions"))
        if isinstance(body, Mapping) and body.get("automation_status") == "OPT_IN":
            self.enabled = frozenset({"text_optimizations"})
        buttons = feed.get("call_to_action_types") or []
        link = feed["link_urls"][0]
        return _present(
            {
                "format": "image" if image else "video",
                "primary_text": _text(body.get("text") if isinstance(body, Mapping) else None),
                "headline": _text(title.get("text") if isinstance(title, Mapping) else None),
                "description": _text(
                    description.get("text") if isinstance(description, Mapping) else None
                ),
                "link": _text(link.get("website_url") if isinstance(link, Mapping) else None),
                "call_to_action": _text(buttons[0]) if buttons else None,
                "media": version(assets["main"]),
                "vertical_media": version(assets["vertical"]),
            }
        )

    def post(self, creative: Mapping[str, Any]) -> tuple[dict[str, Any], str]:
        """An existing post ad: the post, and for Instagram its button and link."""
        if story_id := _text(creative.get("object_story_id")):
            page_id = story_id.split("_", 1)[0]
            post = {"source": "facebook", "post_id": story_id, "page_id": page_id}
            return {"format": "existing_post", "post": self.reference("meta_ads_post", post)}, (
                page_id
            )
        media_id = _text(creative.get("source_instagram_media_id"))
        page_id = _text(creative.get("object_id"))
        instagram = _text(creative.get("instagram_user_id"))
        if media_id is None or page_id is None or instagram is None:
            raise UneditableCreativeError("This ad's creative type can't be edited here.")
        post = {"source": "instagram", "post_id": media_id, "instagram_user_id": instagram}
        content: dict[str, Any] = {
            "format": "existing_post",
            "post": self.reference("meta_ads_post", post),
        }
        link, button = _call_to_action(creative.get("call_to_action"), None)
        if link:
            content.update(link=link, call_to_action=button)
        return content, page_id

    def link_settings(self, data: Mapping[str, Any], link: Any) -> dict[str, Any]:
        cta_link, button = _call_to_action(data.get("call_to_action"), link)
        # Instant experiences open a Meta canvas, which ad creation doesn't build.
        host = (urlsplit(cta_link or "").hostname or "").lower()
        if host == "fb.com" or host.endswith(".fb.com") or "canvas_doc" in (cta_link or ""):
            raise UneditableCreativeError(
                "This ad opens an instant experience, which can't be edited here."
            )
        return {"link": cta_link, "call_to_action": button}

    def image_reference(self, image_hash: str) -> dict[str, Any]:
        self.media[("image", image_hash)] = CreativeImage(image_hash)
        return self.reference(
            "meta_ads_media", {"media_type": "image", "image_hash": image_hash}, "Current image"
        )

    def video_reference(
        self, data: Mapping[str, Any], hash_key: str, url_key: str
    ) -> dict[str, Any]:
        video_id = str(data["video_id"])
        thumbnail_hash = _text(data.get(hash_key))
        self.media[("video", video_id)] = CreativeVideo(
            video_id,
            thumbnail_hash=thumbnail_hash,
            thumbnail_url=None if thumbnail_hash else _text(data.get(url_key)),
        )
        return self.reference(
            "meta_ads_media", {"media_type": "video", "video_id": video_id}, "Current video"
        )

    def image_feed_asset(self, asset: Mapping[str, Any]) -> dict[str, Any]:
        image_hash = _text(asset.get("hash"))
        if image_hash is None:
            raise UneditableCreativeError("This ad's image isn't in the media library.")
        return self.image_reference(image_hash)

    def video_feed_asset(self, asset: Mapping[str, Any]) -> dict[str, Any]:
        if not asset.get("video_id"):
            raise UneditableCreativeError("This ad's video isn't in the media library.")
        return self.video_reference(asset, "thumbnail_hash", "thumbnail_url")

    def reference(
        self, entity_kind: str, fields: Mapping[str, Any], label: str = "Current post"
    ) -> dict[str, Any]:
        return {"entity_kind": entity_kind, "account_id": self.account_id, "label": label, **fields}


def _call_to_action(value: Any, link: Any) -> tuple[str | None, str | None]:
    """Returns the button's link and type; a lead form or app link can't be rebuilt."""
    if not isinstance(value, Mapping):
        return _text(link), None
    details = value.get("value")
    if isinstance(details, Mapping):
        if set(details) - {"link"}:
            raise UneditableCreativeError(
                "This ad's button opens a form, app, or other destination Praxis can't keep."
            )
        link = details.get("link") or link
    return _text(link), _text(value.get("type"))


def _disclaimer(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, Mapping):
        return None
    kind = _DISCLAIMER_TYPES.get(str(value.get("title") or ""))
    if kind is None:
        raise UneditableCreativeError("This ad's disclaimer can't be kept here.")
    return _present(
        {"type": kind, "text": _text(value.get("text")), "url": _text(value.get("url"))}
    )


def _only(value: Mapping[str, Any], allowed: frozenset[str], subject: str) -> None:
    if unknown := sorted(set(value) - allowed):
        raise UneditableCreativeError(
            f"{subject} uses a setting Praxis can't keep ({unknown[0]}), so it can't be edited "
            "here. Create a new ad instead, or edit it in Ads Manager."
        )


def _label(asset: Any) -> str | None:
    labels = asset.get("adlabels") if isinstance(asset, Mapping) else None
    names = [item.get("name") for item in labels or () if isinstance(item, Mapping)]
    return str(names[0]) if len(names) == 1 else None


def _text(value: Any) -> str | None:
    """Reads text; blank counts as unset, as Praxis sends a space for an empty description."""
    if value is None:
        return None
    text = str(value)
    return text if text.strip() else None


def _present(values: Mapping[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in values.items() if value is not None}
