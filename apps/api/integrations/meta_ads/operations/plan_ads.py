# apps/api/integrations/meta_ads/operations/plan_ads.py

"""Plans ads: places each design in its ad sets and checks it against what those ad sets allow."""

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Literal, Protocol
from urllib.parse import urlsplit

from ..creative_features import enabled_for, has_ai_generated
from ..models import MetaAdsPlacements, MetaAdsPromotedObject
from ..tools.schemas.ads import (
    APP_BUTTONS,
    DEFAULT_BUTTON,
    WEBSITE_BUTTONS,
    MetaAdsAdDesign,
    MetaAdsCreateAdsRequest,
    design_media,
    media_key,
)
from ..tools.schemas.objects import CLOSED_STATUSES

_MAX_AD_NAME = 400
_STORIES_AND_REELS = frozenset(
    {
        "facebook",
        "instagram",
        "facebook:story",
        "facebook:facebook_reels",
        "instagram:story",
        "instagram:reels",
    }
)
# Delivery that needs data this tool doesn't collect, such as an instant form.
_PENDING_DESTINATIONS = frozenset(
    {"ON_AD", "MESSENGER", "WHATSAPP", "INSTAGRAM_DIRECT", "PHONE_CALL"}
)
_PENDING_GOALS = frozenset({"LEAD_GENERATION", "QUALITY_LEAD", "CONVERSATIONS"})


class AdSetFacts(Protocol):
    """The ad set details ad creation checks, from a reference or a live read."""

    @property
    def status(self) -> str | None: ...
    @property
    def objective(self) -> str | None: ...
    @property
    def optimization_goal(self) -> str | None: ...
    @property
    def destination_type(self) -> str | None: ...
    @property
    def promoted_object(self) -> MetaAdsPromotedObject | None: ...
    @property
    def placements(self) -> MetaAdsPlacements | None: ...
    @property
    def is_dynamic_creative(self) -> bool | None: ...


@dataclass(frozen=True, slots=True)
class PlannedAd:
    """One ad to create: a design placed in one ad set, with shared values applied."""

    index: int
    design_index: int
    design: MetaAdsAdDesign
    adset_id: str
    adset_name: str | None
    name: str
    status: Literal["paused", "active"]
    link: str
    call_to_action: str
    url_tags: str | None
    enabled: frozenset[str]

    @property
    def key(self) -> str:
        return f"ad:{self.index}"


def ad_set_problem(ad_set: AdSetFacts) -> str | None:
    """Returns why ads can't be added to this ad set by this tool, or None."""
    if ad_set.status in CLOSED_STATUSES:
        return "This ad set is archived or deleted."
    if ad_set.is_dynamic_creative:
        return (
            "This ad set uses dynamic creative, which holds a single special ad. "
            "Choose another ad set."
        )
    if (ad_set.destination_type or "") in _PENDING_DESTINATIONS or (
        ad_set.destination_type or ""
    ).startswith("MESSAG"):
        return "Ads for instant forms, calls, and messages can't be created here yet."
    if (ad_set.optimization_goal or "") in _PENDING_GOALS:
        return "Lead and messaging ads can't be created here yet."
    return None


def design_problem(
    design: MetaAdsAdDesign, request: MetaAdsCreateAdsRequest, ad_sets: Mapping[str, AdSetFacts]
) -> str | None:
    """Checks one design against its ad sets: buttons, links, and vertical versions."""
    if design.link is None and request.link is None:
        return "Add a link, for every ad or for this ad."
    buttons = [design.call_to_action or request.call_to_action or DEFAULT_BUTTON]
    buttons.extend(card.call_to_action for card in design.cards or () if card.call_to_action)
    for reference in design.ad_sets:
        ad_set = ad_sets.get(reference.adset_id)
        if ad_set is None:
            return "One of this ad's ad sets is no longer available. Choose it again."
        if problem := ad_set_problem(ad_set):
            return problem
        allowed = APP_BUTTONS if ad_set.objective == "OUTCOME_APP_PROMOTION" else WEBSITE_BUTTONS
        if invalid := [button for button in buttons if button not in allowed]:
            return f"{invalid[0]} isn't available for this ad set's goal."
        if design.vertical_media is not None and not _shows_stories(ad_set.placements):
            return (
                "This ad set doesn't show ads in Stories or Reels, so the vertical version "
                "has no effect. Remove it or choose another ad set."
            )
    return None


def plan_ads(
    request: MetaAdsCreateAdsRequest, ad_set_names: Mapping[str, str | None]
) -> list[PlannedAd]:
    """Places every design in each of its ad sets, applying shared values and overrides.

    An AI-generated change makes every ad start off, because Meta asks for those ads to
    be previewed before they run.
    """
    enabled = list(request.automatic_changes or ())
    forced_off = has_ai_generated(enabled)
    planned: list[PlannedAd] = []
    for design_index, design in enumerate(request.ads):
        for reference in design.ad_sets:
            adset_name = ad_set_names.get(reference.adset_id) or reference.label
            name = design.name.strip()
            if len(design.ad_sets) > 1:
                name = f"{name} | {adset_name}"
            planned.append(
                PlannedAd(
                    index=len(planned),
                    design_index=design_index,
                    design=design,
                    adset_id=reference.adset_id,
                    adset_name=adset_name,
                    name=name[:_MAX_AD_NAME],
                    status="paused" if forced_off else (design.status or request.status),
                    link=design.link or request.link or "",
                    call_to_action=design.call_to_action
                    or request.call_to_action
                    or DEFAULT_BUTTON,
                    url_tags=design.url_tags or request.url_tags,
                    enabled=enabled_for(design.format, enabled),
                )
            )
    return planned


def duplicate_name(planned: Sequence[PlannedAd], existing: Mapping[str, set[str]]) -> str | None:
    """Returns an ad name used twice in one ad set, by this call or by an ad already there.

    Unique names let a lost create be found again by name.
    """
    seen: set[tuple[str, str]] = set()
    for ad in planned:
        key = (ad.adset_id, ad.name.casefold())
        if key in seen or ad.name.casefold() in existing.get(ad.adset_id, set()):
            return ad.name
        seen.add(key)
    return None


def _text_fingerprints(design: MetaAdsAdDesign) -> dict[str, str]:
    """Returns SHA-256 hashes of the ad's public text, so evidence never holds the text."""
    values = {
        "primary_text": design.primary_text,
        "headline": design.headline,
        "description": design.description,
        "cards": json.dumps(
            [[card.headline, card.description] for card in design.cards or ()],
            ensure_ascii=False,
        )
        if design.cards
        else None,
    }
    return {
        f"{key}_sha256": hashlib.sha256(value.encode()).hexdigest()
        for key, value in values.items()
        if value
    }


def intent_fields(ad: PlannedAd) -> dict[str, str]:
    """Records what is sent without the public text itself: text hashes and the link domain."""
    media = ",".join(":".join(media_key(item)) for item in design_media(ad.design))
    fields = {
        "key": ad.key,
        "design_index": str(ad.design_index),
        "adset_id": ad.adset_id,
        "format": ad.design.format,
        "status": ad.status,
        "call_to_action": ad.call_to_action,
        "link_domain": (urlsplit(ad.link).hostname or "").lower(),
        "media": media[:1000],
        "automatic_changes": ",".join(sorted(ad.enabled)) or "none",
        **_text_fingerprints(ad.design),
    }
    if ad.design.vertical_media is not None:
        fields["vertical"] = "true"
    return fields


def _shows_stories(placements: MetaAdsPlacements | None) -> bool:
    # Unknown placements could include Stories, so only known manual ones are checked.
    if placements is None or placements.mode == "automatic":
        return True
    return bool(_STORIES_AND_REELS.intersection(placements.positions))
