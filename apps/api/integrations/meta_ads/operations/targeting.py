# apps/api/integrations/meta_ads/operations/targeting.py

"""Typed Meta ad set targeting, its local rules, and its mapping to Meta's targeting spec."""

import re
from typing import Annotated, Any, Literal, Self

from pydantic import Field, model_validator

from ..models import MetaAdsStrictModel, MetaAdsText
from ..references import MetaAdsAudienceReference

type MetaAdsLocationKind = Literal["country", "region", "city", "postcode"]
type MetaAdsDetailedKind = Literal["interest", "behavior", "demographic"]
type MetaAdsTargetingKey = Annotated[str, Field(min_length=1, max_length=64)]
type MetaAdsCountryCode = Annotated[str, Field(pattern=r"^[A-Z]{2}$")]

# Demographic groups whose items go in flexible_spec as {id} under Meta's own targeting type.
DEMOGRAPHIC_CATEGORIES = frozenset({"family_statuses", "industries", "income", "life_events"})
_LOCATION_KEYS = {
    "country": re.compile(r"^[A-Z]{2}$"),
    "region": re.compile(r"^[0-9]{1,32}$"),
    "city": re.compile(r"^[0-9]{1,32}$"),
    "postcode": re.compile(r"^[A-Z]{2}:[A-Za-z0-9 -]{1,16}$"),
}
_RADIUS_BOUNDS = {"mile": (10, 50), "kilometer": (17, 80)}
# Special ad categories need a wider city radius in the United States and Canada.
_SPECIAL_RADIUS_MINIMUMS = {"mile": 15, "kilometer": 25}
_SPECIAL_RADIUS_COUNTRIES = frozenset({"US", "CA"})
_LOCATION_EDGES = {"region": "regions", "city": "cities", "postcode": "zips"}
_DETAILED_EDGES = {"interest": "interests", "behavior": "behaviors"}
_GENDERS = {"men": [1], "women": [2]}


class MetaAdsLocation(MetaAdsStrictModel):
    kind: MetaAdsLocationKind
    key: MetaAdsTargetingKey = Field(description="Key from meta_ads_search_targeting.")
    name: MetaAdsText | None = Field(default=None, description="Display only.")
    country_code: MetaAdsCountryCode | None = None
    radius: int | None = Field(default=None, description="Cities only.")
    radius_unit: Literal["mile", "kilometer"] | None = None

    @model_validator(mode="after")
    def _valid_key_and_radius(self) -> Self:
        if not _LOCATION_KEYS[self.kind].fullmatch(self.key):
            raise ValueError(f"Use a {self.kind} key from meta_ads_search_targeting.")
        if (self.radius is None) != (self.radius_unit is None):
            raise ValueError("Give radius and radius_unit together.")
        if self.radius is not None and self.radius_unit is not None:
            if self.kind != "city":
                raise ValueError("Only cities take a radius.")
            low, high = _RADIUS_BOUNDS[self.radius_unit]
            if not low <= self.radius <= high:
                raise ValueError(f"A city radius in {self.radius_unit}s is {low} to {high}.")
        return self


class MetaAdsDetailedItem(MetaAdsStrictModel):
    kind: MetaAdsDetailedKind
    key: Annotated[str, Field(pattern=r"^[0-9]{1,32}$")] = Field(
        description="Key from meta_ads_search_targeting."
    )
    name: MetaAdsText | None = Field(default=None, description="Display only.")
    # Meta's targeting type for a demographic, from meta_ads_search_targeting.
    category: Annotated[str, Field(pattern=r"^[a-z_]{1,64}$")] | None = None

    @model_validator(mode="after")
    def _demographic_category(self) -> Self:
        if (self.kind == "demographic") != (self.category in DEMOGRAPHIC_CATEGORIES):
            raise ValueError("Demographics need the category meta_ads_search_targeting returned.")
        return self


class MetaAdsTargeting(MetaAdsStrictModel):
    """Who an ad set reaches, built only from keys meta_ads_search_targeting returned."""

    locations: list[MetaAdsLocation] = Field(min_length=1, max_length=200)
    excluded_locations: list[MetaAdsLocation] = Field(default_factory=list, max_length=200)
    location_types: Literal["home_or_recent", "home"] = "home_or_recent"
    age_min: int = Field(default=18, ge=13, le=65)
    # Null reaches 65 and over.
    age_max: int | None = Field(default=None, ge=13, le=65)
    genders: Literal["all", "men", "women"] = "all"
    languages: list[Annotated[str, Field(pattern=r"^[0-9]{1,16}$")]] = Field(
        default_factory=list, max_length=50, description="Language keys."
    )
    # Groups are combined with AND; items within a group with OR.
    detailed: list[Annotated[list[MetaAdsDetailedItem], Field(min_length=1, max_length=25)]] = (
        Field(
            default_factory=list,
            max_length=5,
            description="Up to 5 groups; people must match one item from every group.",
        )
    )
    audiences: list[MetaAdsAudienceReference] = Field(default_factory=list, max_length=25)
    excluded_audiences: list[MetaAdsAudienceReference] = Field(default_factory=list, max_length=25)
    advantage_audience: bool = Field(
        default=True,
        description="Let Meta reach beyond age and gender when it expects better results.",
    )

    @model_validator(mode="after")
    def _age_range(self) -> Self:
        if self.age_max is not None and self.age_max < self.age_min:
            raise ValueError("age_max must be at least age_min.")
        return self


def targeting_problems(targeting: MetaAdsTargeting, *, special_category: bool) -> list[str]:
    """Lists what Meta would refuse in a draft, so it's fixed before any request."""
    problems: list[str] = []
    if targeting.advantage_audience and (
        targeting.age_max is not None or not 18 <= targeting.age_min <= 25
    ):
        problems.append(
            "With Advantage+ audience on, age_min must be 18 to 25 and age_max must be empty; "
            "turn advantage_audience off to set a fixed age range."
        )
    if special_category:
        problems.extend(_special_category_problems(targeting))
    return problems


def _special_category_problems(targeting: MetaAdsTargeting) -> list[str]:
    problems: list[str] = []
    if targeting.age_min != 18 or targeting.age_max not in (None, 65):
        problems.append("Housing, employment, and financial ads must reach ages 18 to 65+.")
    if targeting.genders != "all":
        problems.append("Housing, employment, and financial ads can't target by gender.")
    if any(location.kind == "postcode" for location in targeting.locations):
        problems.append("Housing, employment, and financial ads can't target postcodes.")
    if targeting.excluded_locations:
        problems.append("Housing, employment, and financial ads can't exclude locations.")
    if any(
        location.country_code in _SPECIAL_RADIUS_COUNTRIES
        and location.radius is not None
        and location.radius_unit is not None
        and location.radius < _SPECIAL_RADIUS_MINIMUMS[location.radius_unit]
        for location in targeting.locations
    ):
        problems.append(
            "In the US and Canada, these ads need a city radius of at least 15 miles or 25 km."
        )
    if any(item.kind != "interest" for group in targeting.detailed for item in group):
        problems.append(
            "Housing, employment, and financial ads can't use behaviours or demographics."
        )
    if any(audience.subtype == "lookalike" for audience in targeting.audiences):
        problems.append("Housing, employment, and financial ads can't use lookalike audiences.")
    return problems


def targeting_spec(targeting: MetaAdsTargeting) -> dict[str, Any]:
    """Maps the typed draft to Meta's targeting spec, always stating Advantage+ audience."""
    geo = _geo_locations(targeting.locations)
    geo["location_types"] = (
        ["home", "recent"] if targeting.location_types == "home_or_recent" else ["home"]
    )
    spec: dict[str, Any] = {
        "geo_locations": geo,
        "age_min": targeting.age_min,
        "targeting_automation": {"advantage_audience": int(targeting.advantage_audience)},
    }
    if targeting.excluded_locations:
        spec["excluded_geo_locations"] = _geo_locations(targeting.excluded_locations)
    if targeting.age_max is not None:
        spec["age_max"] = targeting.age_max
    if targeting.genders != "all":
        spec["genders"] = _GENDERS[targeting.genders]
    if targeting.languages:
        spec["locales"] = [int(key) for key in targeting.languages]
    if targeting.detailed:
        spec["flexible_spec"] = [_detailed_group(group) for group in targeting.detailed]
    if targeting.audiences:
        spec["custom_audiences"] = [{"id": item.audience_id} for item in targeting.audiences]
    if targeting.excluded_audiences:
        spec["excluded_custom_audiences"] = [
            {"id": item.audience_id} for item in targeting.excluded_audiences
        ]
    return spec


def _geo_locations(locations: list[MetaAdsLocation]) -> dict[str, Any]:
    geo: dict[str, Any] = {}
    for location in locations:
        if location.kind == "country":
            geo.setdefault("countries", []).append(location.key)
            continue
        item: dict[str, Any] = {"key": location.key}
        if location.radius is not None:
            item.update(radius=location.radius, distance_unit=location.radius_unit)
        geo.setdefault(_LOCATION_EDGES[location.kind], []).append(item)
    return geo


def _detailed_group(group: list[MetaAdsDetailedItem]) -> dict[str, list[dict[str, str]]]:
    spec: dict[str, list[dict[str, str]]] = {}
    for item in group:
        edge = item.category if item.kind == "demographic" else _DETAILED_EDGES[item.kind]
        spec.setdefault(edge or "", []).append({"id": item.key})
    return spec
