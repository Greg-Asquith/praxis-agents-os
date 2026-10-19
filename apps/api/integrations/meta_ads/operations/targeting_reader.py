# apps/api/integrations/meta_ads/operations/targeting_reader.py

"""Reads an ad set's targeting spec into the typed draft, and writes a changed draft back over it.

Each section of the draft owns some spec keys. A changed section is written whole from the
draft; every other key, including ones Praxis doesn't model, goes back exactly as Meta returned it.
"""

import copy
import hashlib
import json
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Literal, get_args

from pydantic import Field, ValidationError

from services.integrations.report_results import ReportResultBudget

from ..client import MetaAdsClient, ad_account_path
from ..references import MetaAdsAudienceReference
from .paging import read_pages
from .targeting import (
    DEMOGRAPHIC_CATEGORIES,
    MetaAdsLocation,
    MetaAdsTargeting,
    targeting_spec,
)
from .values import invalid_response

type MetaAdsTargetingSection = Literal[
    "locations",
    "excluded_locations",
    "ages",
    "genders",
    "languages",
    "detailed",
    "audiences",
    "excluded_audiences",
    "advantage_audience",
]
TARGETING_SECTIONS: tuple[MetaAdsTargetingSection, ...] = get_args(
    MetaAdsTargetingSection.__value__
)
SECTION_KEYS: dict[MetaAdsTargetingSection, tuple[str, ...]] = {
    "locations": ("geo_locations",),
    "excluded_locations": ("excluded_geo_locations",),
    "ages": ("age_min", "age_max"),
    "genders": ("genders",),
    "languages": ("locales",),
    "detailed": ("flexible_spec",),
    "audiences": ("custom_audiences",),
    "excluded_audiences": ("excluded_custom_audiences",),
    "advantage_audience": ("targeting_automation",),
}
_FIELD_SECTIONS: dict[str, MetaAdsTargetingSection] = {
    "locations": "locations",
    "location_types": "locations",
    "excluded_locations": "excluded_locations",
    "age_min": "ages",
    "age_max": "ages",
    "genders": "genders",
    "languages": "languages",
    "detailed": "detailed",
    "audiences": "audiences",
    "excluded_audiences": "excluded_audiences",
    "advantage_audience": "advantage_audience",
}
_OPERATION = "update_targeting"
_GEO_EDGES = {"regions": "region", "cities": "city", "zips": "postcode"}
# Fields Meta returns on a region, city, or postcode; any other is a shape Praxis doesn't model.
_PLACE_KEYS = frozenset(
    {"key", "name", "country", "country_name", "region", "region_id", "radius", "distance_unit"}
    | {"primary_city_id", "type"}
)
_LOCATION_TYPES = {("home", "recent"): "home_or_recent", ("home",): "home"}
_DETAILED_KINDS = {"interests": "interest", "behaviors": "behavior"}
# Detailed targeting outside flexible_spec, which Meta treats as one more required group.
_LOOSE_DETAILED = frozenset({*_DETAILED_KINDS, *DEMOGRAPHIC_CATEGORIES})
_GENDERS = {(): "all", (1, 2): "all", (1,): "men", (2,): "women"}
_UNMODELLED = {
    "locations": "pins, markets, or other places Praxis can't change",
    "excluded_locations": "pins, markets, or other places Praxis can't change",
    "ages": "an age range Praxis can't change",
    "genders": "a gender setting Praxis can't change",
    "languages": "languages Praxis can't change",
    "detailed": "job titles, education, or other detailed targeting Praxis can't change",
    "audiences": "audiences Praxis can't change",
    "excluded_audiences": "audiences Praxis can't change",
    "advantage_audience": "an Advantage+ audience setting Praxis can't change",
}


class MetaAdsTargetingRead(MetaAdsTargeting):
    """A draft read from an existing ad set, whose places may all be ones Praxis doesn't model."""

    locations: list[MetaAdsLocation] = Field(default_factory=list, max_length=200)


@dataclass(frozen=True, slots=True)
class MetaAdsReadTargeting:
    """An ad set's targeting as Meta returned it, its draft, and what the draft can't express."""

    spec: dict[str, Any]
    draft: MetaAdsTargetingRead
    # What each section holds that the draft can't express; those sections can't be changed.
    unmodelled: dict[MetaAdsTargetingSection, str]


async def read_targeting_specs(
    client: MetaAdsClient, *, account_id: str, adset_ids: Sequence[str]
) -> dict[str, dict[str, Any]]:
    """Reads each ad set's whole targeting spec, in any status, by ID."""
    ids = sorted(set(adset_ids))
    specs: dict[str, dict[str, Any]] = {}
    for start in range(0, len(ids), 50):
        chunk = ids[start : start + 50]
        rows, _truncated = await read_pages(
            client,
            path=f"{ad_account_path(account_id)}/adsets",
            account_id=account_id,
            params={
                "fields": "id,targeting",
                "filtering": json.dumps([{"field": "id", "operator": "IN", "value": chunk}]),
            },
            limit=len(chunk),
            budget=ReportResultBudget("meta_ads", _OPERATION),
            operation=_OPERATION,
        )
        for row in rows:
            spec = row.get("targeting")
            if row.get("id") in chunk and spec is not None:
                if not isinstance(spec, dict):
                    raise invalid_response(
                        "Meta Ads returned invalid targeting.", operation=_OPERATION
                    )
                specs[row["id"]] = spec
    return specs


def read_targeting(
    spec: Mapping[str, Any],
    *,
    account_id: str,
    audiences: Mapping[str, MetaAdsAudienceReference] | None = None,
) -> MetaAdsReadTargeting:
    """Maps the spec's modelled keys into a draft and names the sections it can't express.

    Audiences come from `audiences` by ID when the account lists them, with their subtype;
    otherwise from the name in the spec.
    """
    known = audiences or {}
    unmodelled: dict[MetaAdsTargetingSection, str] = {}
    fields: dict[str, Any] = {}
    readers = (
        ("locations", lambda: _read_geo(spec.get("geo_locations"), with_types=True)),
        ("excluded_locations", lambda: _read_geo(spec.get("excluded_geo_locations"))),
        ("ages", lambda: _read_ages(spec)),
        ("genders", lambda: _read_genders(spec.get("genders"))),
        ("languages", lambda: _read_languages(spec.get("locales"))),
        ("detailed", lambda: _read_detailed(spec)),
        (
            "audiences",
            lambda: _read_audiences(spec.get("custom_audiences"), "audiences", account_id, known),
        ),
        (
            "excluded_audiences",
            lambda: _read_audiences(
                spec.get("excluded_custom_audiences"), "excluded_audiences", account_id, known
            ),
        ),
        ("advantage_audience", lambda: _read_advantage(spec.get("targeting_automation"))),
    )
    for section, reader in readers:
        values = reader()
        if values is None:
            unmodelled[section] = _UNMODELLED[section]
        else:
            fields.update(values)
    return MetaAdsReadTargeting(
        spec=copy.deepcopy(dict(spec)),
        draft=_validated(fields, unmodelled),
        unmodelled=unmodelled,
    )


def _validated(
    fields: dict[str, Any], unmodelled: dict[MetaAdsTargetingSection, str]
) -> MetaAdsTargetingRead:
    """Validates the draft, marking a section that breaks a draft rule as unmodelled instead."""
    for _ in TARGETING_SECTIONS:
        try:
            return MetaAdsTargetingRead.model_validate(fields)
        except ValidationError as exc:
            # Only the age range rule checks the whole draft, so an error without a field is ages.
            field = next(
                (str(error["loc"][0]) for error in exc.errors() if error["loc"]), "age_min"
            )
            section = _FIELD_SECTIONS.get(field)
            if section is None:
                raise
            unmodelled[section] = _UNMODELLED[section]
            for name, owner in _FIELD_SECTIONS.items():
                if owner == section:
                    fields.pop(name, None)
    return MetaAdsTargetingRead.model_validate(fields)


def _read_geo(value: Any, *, with_types: bool = False) -> dict[str, Any] | None:
    if value is None:
        return {}
    if not isinstance(value, dict):
        return None
    allowed = {"countries", *_GEO_EDGES, *(("location_types",) if with_types else ())}
    if set(value) - allowed:
        return None
    locations: list[dict[str, Any]] = [
        {"kind": "country", "key": code} for code in value.get("countries") or []
    ]
    for edge, kind in _GEO_EDGES.items():
        for item in value.get(edge) or []:
            if not isinstance(item, dict) or set(item) - _PLACE_KEYS:
                return None
            place: dict[str, Any] = {
                "kind": kind,
                "key": str(item.get("key")),
                "name": item.get("name"),
                "country_code": item.get("country"),
            }
            if "radius" in item:
                place.update(radius=item.get("radius"), radius_unit=item.get("distance_unit"))
            locations.append(place)
    try:
        parsed = [MetaAdsLocation.model_validate(item).model_dump() for item in locations]
    except ValidationError:
        return None
    if not with_types:
        return {"excluded_locations": parsed}
    types = _LOCATION_TYPES.get(tuple(sorted(value.get("location_types") or ["home", "recent"])))
    if types is None:
        return None
    return {"locations": parsed, "location_types": types}


def _read_ages(spec: Mapping[str, Any]) -> dict[str, Any] | None:
    age_min = spec.get("age_min", 18)
    age_max = spec.get("age_max")
    if not isinstance(age_min, int) or not (age_max is None or isinstance(age_max, int)):
        return None
    # 65 is Meta's top age, which the draft writes as no maximum.
    return {"age_min": age_min, "age_max": None if age_max == 65 else age_max}


def _read_genders(value: Any) -> dict[str, Any] | None:
    if value is not None and not isinstance(value, list):
        return None
    genders = _GENDERS.get(tuple(sorted(value or [])))
    return None if genders is None else {"genders": genders}


def _read_languages(value: Any) -> dict[str, Any] | None:
    if value is None:
        return {}
    if not isinstance(value, list) or not all(
        isinstance(item, int) and not isinstance(item, bool) for item in value
    ):
        return None
    return {"languages": [str(item) for item in value]}


def _read_detailed(spec: Mapping[str, Any]) -> dict[str, Any] | None:
    if _LOOSE_DETAILED.intersection(spec):
        return None
    groups = spec.get("flexible_spec")
    if groups is None:
        return {}
    if not isinstance(groups, list):
        return None
    detailed: list[list[dict[str, Any]]] = []
    for group in groups:
        if not isinstance(group, dict):
            return None
        items: list[dict[str, Any]] = []
        for edge, values in group.items():
            kind = _DETAILED_KINDS.get(edge) or (
                "demographic" if edge in DEMOGRAPHIC_CATEGORIES else None
            )
            if kind is None or not isinstance(values, list):
                return None
            for value in values:
                if not isinstance(value, dict):
                    return None
                item = {"kind": kind, "key": str(value.get("id")), "name": value.get("name")}
                if kind == "demographic":
                    item["category"] = edge
                items.append(item)
        detailed.append(items)
    return {"detailed": detailed}


def _read_audiences(
    value: Any,
    field: str,
    account_id: str,
    known: Mapping[str, MetaAdsAudienceReference],
) -> dict[str, Any] | None:
    if value is None:
        return {}
    if not isinstance(value, list) or not all(
        isinstance(item, dict) and isinstance(item.get("id"), str) for item in value
    ):
        return None
    references = []
    for item in value:
        audience_id = item["id"]
        name = item.get("name")
        references.append(
            known.get(audience_id)
            or {
                "account_id": account_id,
                "audience_id": audience_id,
                "label": name
                if isinstance(name, str) and name.strip()
                else f"Audience {audience_id}",
            }
        )
    return {field: references}


def _read_advantage(value: Any) -> dict[str, Any] | None:
    if value is None:
        return {"advantage_audience": False}
    flag = value.get("advantage_audience", 0) if isinstance(value, dict) else None
    if flag not in (0, 1):
        return None
    return {"advantage_audience": flag == 1}


def write_targeting(
    read: MetaAdsReadTargeting,
    draft: MetaAdsTargeting,
    touched: Iterable[MetaAdsTargetingSection],
) -> dict[str, Any]:
    """Writes the touched sections from `draft` over the spec as read, keeping every other key."""
    spec = copy.deepcopy(read.spec)
    built = targeting_spec(draft)
    for section in touched:
        if section == "advantage_audience":
            automation = spec.get("targeting_automation")
            spec["targeting_automation"] = {
                **(automation if isinstance(automation, dict) else {}),
                **built["targeting_automation"],
            }
            continue
        for key in SECTION_KEYS[section]:
            spec.pop(key, None)
            if key in built:
                spec[key] = built[key]
    return spec


def section_fingerprints(spec: Mapping[str, Any]) -> dict[MetaAdsTargetingSection, str]:
    """Fingerprints each section's keys as read, so a later read shows which sections changed."""
    return {
        section: hashlib.sha256(
            json.dumps([spec.get(key) for key in keys], sort_keys=True).encode()
        ).hexdigest()[:16]
        for section, keys in SECTION_KEYS.items()
    }


def section_values(draft: MetaAdsTargeting) -> dict[MetaAdsTargetingSection, str]:
    """Describes each section by keys only, in a stable order, for evidence and read-back checks."""
    return {
        "locations": f"{_places(draft.locations)}; {draft.location_types}",
        "excluded_locations": _places(draft.excluded_locations),
        "ages": f"{draft.age_min}-{draft.age_max or '65+'}",
        "genders": draft.genders,
        "languages": ",".join(sorted(draft.languages)) or "all",
        "detailed": " & ".join(
            sorted("|".join(sorted(item.key for item in group)) for group in draft.detailed)
        )
        or "none",
        "audiences": ",".join(sorted(item.audience_id for item in draft.audiences)) or "none",
        "excluded_audiences": ",".join(
            sorted(item.audience_id for item in draft.excluded_audiences)
        )
        or "none",
        "advantage_audience": "on" if draft.advantage_audience else "off",
    }


def _places(locations: Sequence[MetaAdsLocation]) -> str:
    keys = (
        f"{item.kind}:{item.key}"
        + (f"+{item.radius}{item.radius_unit}" if item.radius is not None else "")
        for item in locations
    )
    return ",".join(sorted(keys)) or "none"
