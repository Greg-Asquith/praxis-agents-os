# apps/api/integrations/meta_ads/operations/edit_targeting.py

"""Applies targeting additions and removals to one ad set's draft, with Meta's rules."""

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any, Literal

from pydantic import ValidationError

from ..references import MetaAdsAudienceReference
from ..tools.schemas.targeting_edits import MetaAdsLocationKey, MetaAdsTargetingEdit
from .create_ad_set import EU_NAMES_MISSING, includes_eu
from .edit_impact import (
    AUTOMATIC_PLACEMENTS_NOTE,
    EU_DEFAULTS_NOTE,
    MANUAL_PLACEMENTS_NOTE,
    STATED_ADVANTAGE_NOTE,
)
from .targeting import (
    MetaAdsDetailedItem,
    MetaAdsLocation,
    targeting_countries,
    targeting_problems,
)
from .targeting_reader import (
    POSITIONS,
    RETIRED_POSITIONS,
    MetaAdsInventoryFilter,
    MetaAdsReadTargeting,
    MetaAdsTargetingRead,
    MetaAdsTargetingSection,
    write_targeting,
)

type MetaAdsEuNames = Literal["not_needed", "sent", "account_defaults"]

_RETIRED_ONLY = (
    "This ad set shows ads only in placements Meta no longer offers. Change its placements in "
    "Ads Manager first."
)
_SECTION_NAMES: dict[MetaAdsTargetingSection, str] = {
    "locations": "locations",
    "excluded_locations": "excluded locations",
    "ages": "ages",
    "genders": "genders",
    "languages": "languages",
    "detailed": "detailed targeting",
    "audiences": "audiences",
    "excluded_audiences": "excluded audiences",
    "advantage_audience": "Advantage+ audience",
    "placements": "placements",
    "inventory_filter": "inventory filter",
}
_PLATFORM_NAMES = {
    "facebook": "Facebook",
    "instagram": "Instagram",
    "audience_network": "Audience Network",
    "messenger": "Messenger",
    "threads": "Threads",
}
_FILTER_RANKS = {"expanded": 0, "moderate": 1, "limited": 2}
_FILTER_LOOSER = (
    "The ad account's inventory filter is stricter; change it in Brand Safety settings."
)


@dataclass
class MetaAdsTargetingChange:
    """One ad set's targeting before and after an edit, the spec to send, and what blocks it."""

    before: MetaAdsTargetingRead
    after: MetaAdsTargetingRead
    sections: tuple[MetaAdsTargetingSection, ...]
    spec: dict[str, Any]
    eu_names: MetaAdsEuNames = "not_needed"
    problems: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


def edit_targeting(
    edit: MetaAdsTargetingEdit,
    read: MetaAdsReadTargeting,
    *,
    special_category: bool,
    reached_eu: bool,
    has_eu_names: bool,
    eu_defaults: bool,
    advantage_campaign: bool = False,
    account_filter: MetaAdsInventoryFilter | None = None,
) -> MetaAdsTargetingChange:
    """Applies the edit to the read draft and builds the whole spec to send.

    `reached_eu` says whether the ad set reaches the EU before the edit, `has_eu_names` whether
    it already names its EU payer and beneficiary, and `eu_defaults` whether the ad account has
    defaults for both. `advantage_campaign` says whether the campaign qualifies as Advantage+
    now, and `account_filter` is the ad account's inventory filter, when it could be read.
    """
    before = read.draft
    change = MetaAdsTargetingChange(
        before=before, after=before, sections=edit.sections, spec=read.spec
    )
    for section in edit.sections:
        if section in read.unmodelled:
            change.problems.append(
                f"This ad set's {_SECTION_NAMES[section]} include {read.unmodelled[section]}, "
                "so change them in Ads Manager."
            )
    if change.problems:
        return change
    fields = before.model_dump()
    change.problems.extend(_apply(edit, fields))
    if change.problems:
        return change
    try:
        change.after = MetaAdsTargetingRead.model_validate(fields)
    except ValidationError as exc:
        change.problems.append(exc.errors()[0]["msg"].removeprefix("Value error, "))
        return change
    change.problems.extend(_rule_problems(edit, change, special_category=special_category))
    change.problems.extend(_filter_problems(edit, change.after, account_filter))
    change.notes.extend(_placement_notes(change, advantage_campaign=advantage_campaign))
    sections: tuple[MetaAdsTargetingSection, ...] = edit.sections
    if special_category and not _states_advantage(read.spec):
        # v26 needs Advantage+ audience stated on these ad sets once their targeting changes.
        sections = (*sections, "advantage_audience")
        state = "on" if change.after.advantage_audience else "off"
        change.notes.append(STATED_ADVANTAGE_NOTE.format(state=state))
    change.spec = write_targeting(read, change.after, sections)
    change.problems.extend(_drop_retired_positions(change.spec, change.notes))
    reaches_eu = (
        includes_eu(targeting_countries(change.after))
        if "locations" in edit.sections
        else reached_eu
    )
    change.eu_names, problem = _eu_names(
        edit,
        reached_eu=reached_eu,
        reaches_eu=reaches_eu,
        has_eu_names=has_eu_names,
        eu_defaults=eu_defaults,
    )
    if problem:
        change.problems.append(problem)
    elif change.eu_names == "account_defaults":
        change.notes.append(EU_DEFAULTS_NOTE)
    return change


def _apply(edit: MetaAdsTargetingEdit, fields: dict[str, Any]) -> list[str]:
    """Applies each operation to the draft fields, refusing ones that contradict them."""
    problems = [
        *_edit_list(fields, "locations", edit.add_locations, edit.remove_locations),
        *_edit_list(
            fields,
            "excluded_locations",
            edit.add_excluded_locations,
            edit.remove_excluded_locations,
        ),
        *_edit_list(fields, "audiences", edit.add_audiences, edit.remove_audiences),
        *_edit_list(
            fields,
            "excluded_audiences",
            edit.add_excluded_audiences,
            edit.remove_excluded_audiences,
        ),
        *_detailed(edit, fields),
    ]
    for name in ("location_types", "age_min", "genders", "advantage_audience"):
        if (value := getattr(edit, name)) is not None:
            fields[name] = value
    if edit.age_max is not None:
        fields["age_max"] = None if edit.age_max == "none" else edit.age_max
    if edit.languages is not None:
        fields["languages"] = [] if edit.languages == "all" else list(edit.languages)
    if edit.inventory_filter is not None:
        fields["inventory_filter"] = {
            **fields["inventory_filter"],
            **edit.inventory_filter.model_dump(exclude_none=True),
        }
    return [*problems, *_placements(edit, fields)]


def _placements(edit: MetaAdsTargetingEdit, fields: dict[str, Any]) -> list[str]:
    """Replaces placements, or removes platforms and positions from the ones the ad set has.

    Removing from automatic placements starts from every position Meta offers.
    """
    if edit.placements is not None:
        fields["placements"] = edit.placements.model_dump()
        return []
    if not (edit.remove_platforms or edit.remove_positions):
        return []
    current = fields["placements"]
    positions = current["positions"] if current["mode"] == "manual" else list(POSITIONS)
    platforms = {position.split(":")[0] for position in positions}
    problems = [
        f"This ad set doesn't show ads on {_PLATFORM_NAMES[platform]}, so it can't be removed."
        for platform in edit.remove_platforms
        if platform not in platforms
    ]
    problems.extend(
        f"{position} isn't one of this ad set's placements, so it can't be removed."
        for position in edit.remove_positions
        if position not in positions
    )
    kept = [
        position
        for position in positions
        if position.split(":")[0] not in edit.remove_platforms
        and position not in edit.remove_positions
    ]
    if not kept:
        problems.append("Keep at least one placement.")
    fields["placements"] = {"mode": "manual", "positions": kept, "devices": current["devices"]}
    return problems


def _edit_list(
    fields: dict[str, Any],
    name: str,
    added: Sequence[MetaAdsLocation] | Sequence[MetaAdsAudienceReference],
    removed: Sequence[MetaAdsLocationKey] | Sequence[MetaAdsAudienceReference],
) -> list[str]:
    """Removes then adds places or audiences, refusing ones that contradict the list."""
    current: list[dict[str, Any]] = fields[name]
    keys = {_identity(item) for item in current}
    noun = "excluded" if name.startswith("excluded") else "targeted"
    problems = [
        f"{_label(item)} isn't {noun}, so it can't be removed."
        for item in removed
        if _identity(item.model_dump()) not in keys
    ]
    gone = {_identity(item.model_dump()) for item in removed}
    # Removing and adding the same item replaces it, such as a city with a new radius.
    problems.extend(
        f"{_label(item)} is already {noun}."
        for item in added
        if _identity(item.model_dump()) in keys - gone
    )
    fields[name] = [
        *(item for item in current if _identity(item) not in gone),
        *(item.model_dump() for item in added),
    ]
    return problems


def _identity(item: dict[str, Any]) -> tuple[str, ...]:
    """Identifies an audience by ID and a place by kind and key."""
    return (item["audience_id"],) if "audience_id" in item else (item["kind"], item["key"])


def _label(item: MetaAdsLocation | MetaAdsLocationKey | MetaAdsAudienceReference) -> str:
    if isinstance(item, MetaAdsAudienceReference):
        return item.label
    return item.name or item.key


def _detailed(edit: MetaAdsTargetingEdit, fields: dict[str, Any]) -> list[str]:
    if edit.detailed is not None:
        fields["detailed"] = (
            []
            if edit.detailed == "none"
            else [[item.model_dump() for item in group] for group in edit.detailed]
        )
        return []
    groups: list[list[dict[str, Any]]] = fields["detailed"]
    keys = {item["key"] for group in groups for item in group}
    problems = [
        f"{key} isn't in this ad set's detailed targeting, so it can't be removed."
        for key in edit.remove_detailed_items
        if key not in keys
    ]
    gone = set(edit.remove_detailed_items)
    groups = [[item for item in group if item["key"] not in gone] for group in groups]
    if (addition := edit.add_detailed_items) is not None:
        problems.extend(_add_detailed(groups, addition.group, addition.items, keys))
    fields["detailed"] = [group for group in groups if group]
    return problems


def _add_detailed(
    groups: list[list[dict[str, Any]]],
    group: int,
    items: Sequence[MetaAdsDetailedItem],
    keys: set[str],
) -> list[str]:
    problems = [
        f"{item.name or item.key} is already in this ad set's detailed targeting."
        for item in items
        if item.key in keys
    ]
    if group > len(groups) + 1:
        problems.append(
            f"This ad set has {len(groups)} detailed groups, so use group 1 to {len(groups) + 1}."
        )
        return problems
    if group == len(groups) + 1:
        groups.append([])
    groups[group - 1].extend(item.model_dump() for item in items)
    return problems


def _rule_problems(
    edit: MetaAdsTargetingEdit, change: MetaAdsTargetingChange, *, special_category: bool
) -> list[str]:
    """Lists Meta's rules the change breaks; rules the ad set already broke don't block it."""
    after = change.after
    problems: list[str] = []
    if "locations" in change.sections and not after.locations:
        problems.append("Keep at least one location.")
    existing = set(targeting_problems(change.before, special_category=special_category))
    problems.extend(
        problem
        for problem in targeting_problems(after, special_category=special_category)
        if problem not in existing
    )
    if special_category and edit.advantage_audience is False and change.before.advantage_audience:
        problems.append(
            "Housing, employment, and financial ads keep Advantage+ audience on once it's on."
        )
    return problems


def _filter_problems(
    edit: MetaAdsTargetingEdit,
    after: MetaAdsTargetingRead,
    account_filter: MetaAdsInventoryFilter | None,
) -> list[str]:
    """Refuses an Audience Network filter it can't use, or one looser than the account's."""
    if edit.inventory_filter is None:
        return []
    problems: list[str] = []
    placements = after.placements
    if (
        edit.inventory_filter.audience_network is not None
        and placements.mode == "manual"
        and not any(item.startswith("audience_network:") for item in placements.positions)
    ):
        problems.append(
            "This ad set doesn't show ads on Audience Network, so leave its inventory filter out."
        )
    for platform, level in edit.inventory_filter.model_dump(exclude_none=True).items():
        floor = getattr(account_filter, platform, None) if account_filter else None
        if floor is not None and _FILTER_RANKS[level] < _FILTER_RANKS[floor]:
            problems.append(_FILTER_LOOSER)
            break
    return problems


def _placement_notes(change: MetaAdsTargetingChange, *, advantage_campaign: bool) -> list[str]:
    if "placements" not in change.sections:
        return []
    before, after = change.before.placements.mode, change.after.placements.mode
    if before == "automatic" and after == "manual" and advantage_campaign:
        return [MANUAL_PLACEMENTS_NOTE]
    if before == "manual" and after == "automatic":
        return [AUTOMATIC_PLACEMENTS_NOTE]
    return []


def _states_advantage(spec: dict[str, Any]) -> bool:
    automation = spec.get("targeting_automation")
    return isinstance(automation, dict) and "advantage_audience" in automation


def _drop_retired_positions(spec: dict[str, Any], notes: list[str]) -> list[str]:
    """Removes positions v26 refuses from the spec, noting each; refuses a platform left empty."""
    platforms = spec.get("publisher_platforms")
    for retired, note in RETIRED_POSITIONS.items():
        platform, position = retired.split(":")
        key = f"{platform}_positions"
        positions = spec.get(key)
        if not isinstance(positions, list) or position not in positions:
            continue
        kept = [item for item in positions if item != position]
        if not kept and isinstance(platforms, list) and platform in platforms:
            return [_RETIRED_ONLY]
        spec[key] = kept
        notes.append(note)
    return []


def _eu_names(
    edit: MetaAdsTargetingEdit,
    *,
    reached_eu: bool,
    reaches_eu: bool,
    has_eu_names: bool,
    eu_defaults: bool,
) -> tuple[MetaAdsEuNames, str | None]:
    """Decides how an ad set that newly reaches the EU names its payer, or why it can't."""
    named = edit.eu_payer is not None or edit.eu_beneficiary is not None
    if named and not reaches_eu:
        return "not_needed", (
            "This ad set doesn't reach anyone in the EU, so leave eu_payer and eu_beneficiary out."
        )
    if not reaches_eu or reached_eu or has_eu_names:
        return ("sent" if named else "not_needed"), None
    if edit.eu_payer and edit.eu_beneficiary:
        return "sent", None
    if eu_defaults:
        return "account_defaults", None
    return "not_needed", EU_NAMES_MISSING
