# apps/api/integrations/meta_ads/operations/edit_creative.py

"""Builds an ad's new creative from its live one plus the requested changes.

The merged ad goes through the same model, checks, and creative builder as ad
creation, so an edit can't send what creation would refuse.
"""

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, replace
from typing import Any

from pydantic_ai import ModelRetry

from ..creative_features import OFFERED_CHANGE_KEYS, enabled_for, has_ai_generated
from ..references import (
    MetaAdsInstagramAccountReference,
    MetaAdsMediaReference,
    MetaAdsPageReference,
    MetaAdsPostReference,
)
from ..tools.schemas.ad_edits import MetaAdsCreativeChanges, MetaAdsCreativeField
from ..tools.schemas.ads import (
    DEFAULT_BUTTON,
    MediaKey,
    MetaAdsAdContent,
    design_media,
    media_key,
)
from ..tools.schemas.objects import MetaAdsObject
from ..tools.utils.create_operation import validated
from .create_ads import creative_input
from .creatives import CreativeMedia, CreativeVideo, conversion_domain, creative_spec
from .plan_ads import PlannedAd, design_problem
from .read_creative import LiveCreative

_UPLOAD_FIRST = (
    "Upload new images and videos with meta_ads_upload_media first, then use the media "
    "reference it returns."
)
_NEW_AI_CHANGE = (
    "AI-generated automatic changes can only be turned on for a new ad, which starts off so "
    "you can preview it. Create a new ad with meta_ads_create_ads instead."
)


@dataclass(frozen=True, slots=True)
class _LiveSettings:
    """The one ad's identity, as ad creation's checks read a call's shared settings."""

    ads: Sequence[MetaAdsAdContent]
    page: MetaAdsPageReference
    instagram_account: MetaAdsInstagramAccountReference | None
    automatic_changes: Sequence[str]
    link: str | None = None
    call_to_action: str | None = None
    url_tags: str | None = None


@dataclass
class CreativeEdit:
    """One ad's new creative as checked, and the parts that differ from the live one."""

    live: LiveCreative
    design: MetaAdsAdContent | None
    enabled: frozenset[str]
    changed: tuple[MetaAdsCreativeField, ...] = ()
    problems: list[str] = field(default_factory=list)

    @property
    def new_post(self) -> MetaAdsPostReference | None:
        """The post an existing post ad switches to, which must be read before it's used."""
        if self.design is None or "post" not in self.changed:
            return None
        return self.design.post

    @property
    def new_media(self) -> list[MetaAdsMediaReference]:
        """Library media the live creative doesn't use, which must be read before it's used."""
        if self.design is None:
            return []
        return [
            item
            for item in design_media(self.design)
            if isinstance(item, MetaAdsMediaReference) and media_key(item) not in self.live.media
        ]


def plan_creative_edit(
    live: LiveCreative,
    changes: MetaAdsCreativeChanges,
    *,
    ad: MetaAdsObject,
    ad_set: MetaAdsObject,
    account_id: str,
) -> CreativeEdit:
    """Merges the changes into the live creative and applies ad creation's rules."""
    enabled = _enabled(live, changes)
    try:
        design = validated(MetaAdsAdContent, _merged(live, changes, ad.name or ad.id))
    except ModelRetry as exc:
        return CreativeEdit(live, None, enabled, problems=[str(exc)])
    edit = CreativeEdit(live, design, enabled, changed=_changed(live, design, enabled))
    edit.problems.extend(_problems(edit, ad_set, account_id))
    return edit


def _merged(live: LiveCreative, changes: MetaAdsCreativeChanges, name: str) -> dict[str, Any]:
    values = {**live.content, "name": name}
    requested = changes.model_dump(mode="json", exclude_none=True, exclude={"automatic_changes"})
    for key, value in requested.items():
        if value == "none":
            values.pop(key, None)
        else:
            values[key] = value
    return values


def _enabled(live: LiveCreative, changes: MetaAdsCreativeChanges) -> frozenset[str]:
    """Changes the card doesn't offer stay as Meta has them; offered ones follow the edit."""
    if changes.automatic_changes is None:
        return live.enabled
    ad_format = live.content["format"]
    return (live.enabled - set(OFFERED_CHANGE_KEYS)) | enabled_for(
        ad_format, changes.automatic_changes
    )


def _changed(
    live: LiveCreative, design: MetaAdsAdContent, enabled: frozenset[str]
) -> tuple[MetaAdsCreativeField, ...]:
    after = design.model_dump(mode="json", exclude_none=True)
    changed: list[MetaAdsCreativeField] = [
        key
        for key in MetaAdsCreativeChanges.model_fields
        if key != "automatic_changes" and not _same(live.content.get(key), after.get(key))
    ]
    if enabled != live.enabled:
        changed.append("automatic_changes")
    return tuple(changed)


def _same(before: Any, after: Any) -> bool:
    """Compares media by what they are, not by the label the card shows."""
    return _identity(before) == _identity(after)


def _identity(value: Any) -> Any:
    if isinstance(value, list):
        return [_identity(item) for item in value]
    if not isinstance(value, Mapping):
        return value
    if value.get("entity_kind") in ("meta_ads_media", "meta_ads_post"):
        return (value.get("image_hash"), value.get("video_id"), value.get("post_id"))
    return {key: _identity(item) for key, item in value.items()}


def _problems(edit: CreativeEdit, ad_set: MetaAdsObject, account_id: str) -> list[str]:
    design, live = edit.design, edit.live
    if design is None:
        return []
    if not edit.changed:
        return ["This ad already shows these values, so its creative wouldn't change."]
    if any(not isinstance(item, MetaAdsMediaReference) for item in design_media(design)):
        return [_UPLOAD_FIRST]
    if any(item.account_id != account_id for item in edit.new_media):
        return ["Use media from this ad's own ad account."]
    if has_ai_generated(edit.enabled - live.enabled):
        return [_NEW_AI_CHANGE]
    if live.has_vertical and design.vertical_media is None:
        return [
            "Meta doesn't let an ad with a vertical version drop it. Create a new ad without "
            "one instead."
        ]
    settings = _LiveSettings(
        ads=[design],
        page=MetaAdsPageReference(account_id=account_id, page_id=live.page_id, label="Page"),
        instagram_account=MetaAdsInstagramAccountReference(
            account_id=account_id, instagram_user_id=live.instagram_user_id, label="Instagram"
        )
        if live.instagram_user_id
        else None,
        automatic_changes=sorted(edit.enabled),
    )
    problem = design_problem(design, settings, [ad_set])
    return [problem] if problem else []


def thumbnail_problem(edit: CreativeEdit, media: Mapping[MediaKey, CreativeMedia]) -> str | None:
    """Instagram needs a thumbnail for every video, chosen or Meta's own."""
    design = edit.design
    if design is None:
        return None
    uses = [(design.media, design.thumbnail)]
    uses.extend((card.media, card.thumbnail) for card in design.cards or ())
    for item, chosen in uses:
        video = media.get(media_key(item)) if item is not None else None
        if (
            isinstance(video, CreativeVideo)
            and chosen is None
            and not (video.thumbnail_url or video.thumbnail_hash)
        ):
            return "Add a thumbnail image for the video."
    return None


def creative_body(
    edit: CreativeEdit,
    media: Mapping[MediaKey, CreativeMedia],
    *,
    adset_id: str,
    pixel_id: str | None,
) -> dict[str, str]:
    """The part of `POST /{ad_id}` that switches the ad to its new creative."""
    design, live = edit.design, edit.live
    if design is None:
        raise ValueError("A creative edit with problems has no body")
    facebook_post = design.post is not None and design.post.source == "facebook"
    link = "" if facebook_post else design.link or ""
    planned = PlannedAd(
        index=0,
        design_index=0,
        design=design,
        adset_id=adset_id,
        adset_name=None,
        name=design.name,
        # Status isn't part of the creative; the ad keeps its own.
        status="paused",
        link=link,
        call_to_action=design.call_to_action or DEFAULT_BUTTON,
        url_tags=None if design.post else design.url_tags,
        enabled=edit.enabled,
    )
    item = replace(
        creative_input(planned, live.page_id, live.instagram_user_id, media),
        destination_type=live.destination_type,
        applink_treatment=live.applink_treatment,
        display_link=live.display_link,
    )
    body = {"creative": json.dumps(creative_spec(item), separators=(",", ":"))}
    # Meta requires the destination's domain when the campaign shares data with a pixel.
    if pixel_id and link:
        body["conversion_domain"] = conversion_domain(link)
    return body
