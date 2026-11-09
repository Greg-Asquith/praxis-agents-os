# apps/api/integrations/google_ads/operations/search_targeting.py

"""Finds Google's location and language constants by name, and reads them back by key."""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from services.integrations.http import IntegrationRequestPolicy

from ..client import GoogleAdsClient, normalize_customer_id
from .utils import stream_rows

# Google's limit on names in one suggestion request.
MAX_LOCATION_NAMES = 25
_MAX_IDS_PER_QUERY = 1_000
_MAX_LANGUAGES = 500


@dataclass(frozen=True, slots=True)
class LocationOption:
    key: str
    name: str
    target_type: str | None
    region: str | None
    country_code: str | None
    # Approximate people reached, rounded by Google; only a name search returns it.
    reach: int | None = None
    # The name this option matched, when found by name.
    search_term: str | None = None


@dataclass(frozen=True, slots=True)
class LanguageOption:
    key: str
    name: str
    code: str | None


def _location_option(
    constant: Mapping[str, Any], *, reach: Any = None, search_term: Any = None
) -> LocationOption | None:
    key = str(constant.get("id") or str(constant.get("resourceName", "")).rpartition("/")[2])
    name = constant.get("name")
    if not key.isdigit() or not isinstance(name, str) or not name:
        return None
    canonical = constant.get("canonicalName")
    parents = canonical.split(",")[1:] if isinstance(canonical, str) else []
    return LocationOption(
        key=key,
        name=name,
        target_type=constant.get("targetType"),
        region=", ".join(parents) or None,
        country_code=constant.get("countryCode"),
        reach=int(reach) if str(reach).isdigit() else None,
        search_term=search_term if isinstance(search_term, str) else None,
    )


async def search_locations(
    client: GoogleAdsClient, *, names: Sequence[str], country_code: str | None = None
) -> list[LocationOption]:
    """Returns Google's suggestions for up to 25 location names, best match first per name."""
    if not names or len(names) > MAX_LOCATION_NAMES:
        raise ValueError("Google Ads location search takes between 1 and 25 names")
    payload = await client.post(
        "geoTargetConstants:suggest",
        operation="search_locations",
        policy=IntegrationRequestPolicy.READ,
        json={
            "locale": "en",
            "locationNames": {"names": list(names)},
            **({"countryCode": country_code} if country_code else {}),
        },
    )
    suggestions = payload.get("geoTargetConstantSuggestions") if isinstance(payload, dict) else None
    options: list[LocationOption] = []
    for suggestion in suggestions if isinstance(suggestions, list) else []:
        constant = suggestion.get("geoTargetConstant") if isinstance(suggestion, dict) else None
        if isinstance(constant, Mapping):
            option = _location_option(
                constant, reach=suggestion.get("reach"), search_term=suggestion.get("searchTerm")
            )
            if option is not None:
                options.append(option)
    return options


async def read_locations(
    client: GoogleAdsClient, *, customer_id: str, login_customer_id: str, keys: Sequence[str]
) -> dict[str, LocationOption]:
    """Returns the location constants that exist among the keys, in batches of 1,000."""
    if any(not key.isdigit() for key in keys):
        raise ValueError("Google Ads location keys must contain only digits")
    unique = sorted(set(keys))
    found: dict[str, LocationOption] = {}
    for start in range(0, len(unique), _MAX_IDS_PER_QUERY):
        batch = unique[start : start + _MAX_IDS_PER_QUERY]
        payload = await client.post(
            f"customers/{normalize_customer_id(customer_id)}/googleAds:searchStream",
            operation="read_locations",
            policy=IntegrationRequestPolicy.READ,
            login_customer_id=login_customer_id,
            json={
                "query": (
                    "SELECT geo_target_constant.id, geo_target_constant.name, "  # noqa: S608 -- digit-only ids
                    "geo_target_constant.canonical_name, geo_target_constant.target_type, "
                    "geo_target_constant.country_code FROM geo_target_constant "
                    f"WHERE geo_target_constant.id IN ({', '.join(batch)})"
                )
            },
        )
        for row in stream_rows(payload, max_rows=len(batch)):
            constant = row.get("geoTargetConstant")
            option = _location_option(constant) if isinstance(constant, Mapping) else None
            if option is not None:
                found[option.key] = option
    return found


async def read_languages(
    client: GoogleAdsClient, *, customer_id: str, login_customer_id: str
) -> list[LanguageOption]:
    """Returns every language Google lets campaigns target."""
    payload = await client.post(
        f"customers/{normalize_customer_id(customer_id)}/googleAds:searchStream",
        operation="read_languages",
        policy=IntegrationRequestPolicy.READ,
        login_customer_id=login_customer_id,
        json={
            "query": (
                "SELECT language_constant.id, language_constant.name, language_constant.code "
                "FROM language_constant WHERE language_constant.targetable = TRUE"
            )
        },
    )
    languages: list[LanguageOption] = []
    for row in stream_rows(payload, max_rows=_MAX_LANGUAGES):
        constant = row.get("languageConstant")
        if not isinstance(constant, Mapping):
            continue
        key, name = str(constant.get("id", "")), constant.get("name")
        if key.isdigit() and isinstance(name, str) and name:
            languages.append(LanguageOption(key=key, name=name, code=constant.get("code")))
    return languages


def matching_languages(languages: Sequence[LanguageOption], text: str) -> list[LanguageOption]:
    """Filters by name or exact code, ignoring case; blank text keeps every language."""
    needle = text.strip().casefold()
    return [
        language
        for language in languages
        if needle in language.name.casefold() or needle == (language.code or "").casefold()
    ]
