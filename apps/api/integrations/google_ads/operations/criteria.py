# apps/api/integrations/google_ads/operations/criteria.py

"""Reads campaign and ad group criteria by type, as the live values the edit seam compares."""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Literal

from core.exceptions.integration import IntegrationFailureDisposition, IntegrationValidationError
from services.integrations.http import IntegrationRequestPolicy

from ..client import GoogleAdsClient, normalize_customer_id
from .utils import stream_rows

type CriterionKind = Literal[
    "location",
    "excluded_location",
    "radius",
    "language",
    "device",
    "schedule",
    "audience",
    "demographic",
    "excluded_demographic",
]
type CriterionType = Literal[
    "LOCATION",
    "PROXIMITY",
    "LANGUAGE",
    "DEVICE",
    "AD_SCHEDULE",
    "USER_LIST",
    "USER_INTEREST",
    "CUSTOM_AUDIENCE",
    "COMBINED_AUDIENCE",
    "AGE_RANGE",
    "GENDER",
    "PARENTAL_STATUS",
    "INCOME_RANGE",
]

# The criterion types an ad group can hold; places, devices, and times are set on campaigns.
AD_GROUP_TYPES: tuple[CriterionType, ...] = (
    "USER_LIST",
    "USER_INTEREST",
    "CUSTOM_AUDIENCE",
    "COMBINED_AUDIENCE",
    "AGE_RANGE",
    "GENDER",
    "PARENTAL_STATUS",
    "INCOME_RANGE",
)
# Google allows 10,000 locations a campaign, so this only stops an unbounded read.
_MAX_CRITERIA = 50_000
_SETTING_PATH = "geoTargetTypeSetting.positiveGeoTargetType"
RESTRICTIONS_PATH = "targetingSetting.targetRestrictions"
BID_MODIFIER_PATH = "bidModifier"
# Google's quarter-hour minutes, by the minutes they stand for.
SCHEDULE_MINUTES = {0: "ZERO", 15: "FIFTEEN", 30: "THIRTY", 45: "FORTY_FIVE"}
_MINUTES = {name: minutes for minutes, name in SCHEDULE_MINUTES.items()}
# Strategies that ignore device bid adjustments other than excluding the device.
_IGNORE_DEVICE_BIDS = {"TARGET_ROAS", "MAXIMIZE_CONVERSION_VALUE"}
# Smart Bidding sets bids for each auction, so it ignores time, audience, and demographic
# bid adjustments.
_SMART_BIDDING = {
    "TARGET_CPA",
    "TARGET_ROAS",
    "MAXIMIZE_CONVERSIONS",
    "MAXIMIZE_CONVERSION_VALUE",
}
# Each audience kind's JSON field, and the field in it that names the audience.
AUDIENCE_FIELDS = {
    "user_list": ("userList", "userList", "userLists"),
    "user_interest": ("userInterest", "userInterestCategory", "userInterests"),
    "custom_audience": ("customAudience", "customAudience", "customAudiences"),
    "combined_audience": ("combinedAudience", "combinedAudience", "combinedAudiences"),
}
_AUDIENCE_TYPES = {
    "USER_LIST": "user_list",
    "USER_INTEREST": "user_interest",
    "CUSTOM_AUDIENCE": "custom_audience",
    "COMBINED_AUDIENCE": "combined_audience",
}
# Each demographic dimension's JSON field.
DEMOGRAPHIC_FIELDS = {
    "AGE_RANGE": "ageRange",
    "GENDER": "gender",
    "PARENTAL_STATUS": "parentalStatus",
    "INCOME_RANGE": "incomeRange",
}
_COMMON_FIELDS = ("resource_name", "criterion_id", "type", "negative", "bid_modifier")
_CAMPAIGN_ONLY_FIELDS = (
    "location.geo_target_constant",
    "language.language_constant",
    "proximity.geo_point.latitude_in_micro_degrees",
    "proximity.geo_point.longitude_in_micro_degrees",
    "proximity.radius",
    "proximity.radius_units",
    "device.type",
    "ad_schedule.day_of_week",
    "ad_schedule.start_hour",
    "ad_schedule.start_minute",
    "ad_schedule.end_hour",
    "ad_schedule.end_minute",
)
_SHARED_FIELDS = (
    "user_list.user_list",
    "user_interest.user_interest_category",
    "custom_audience.custom_audience",
    "combined_audience.combined_audience",
    "age_range.type",
    "gender.type",
    "parental_status.type",
    "income_range.type",
)


@dataclass(frozen=True, slots=True)
class LiveCriterion:
    kind: CriterionKind
    # The location or language key, the device type, or the identity from `radius_value`,
    # `schedule_value`, `audience_value`, or `demographic_value`.
    value: str
    resource_name: str
    criterion_id: str
    # 1.0 means no bid adjustment.
    bid_modifier: float = 1.0
    latitude_micro: int | None = None
    longitude_micro: int | None = None
    radius: float | None = None
    units: str | None = None


@dataclass(frozen=True, slots=True)
class LiveTargeting:
    """A campaign's or ad group's targeting as Google shows it now."""

    resource_name: str
    name: str
    status: str
    # The campaign's, for an ad group too.
    channel: str
    location_setting: str | None
    # By `criterion_key`.
    criteria: Mapping[str, LiveCriterion]
    bidding_strategy: str | None = None
    # Maximize Conversions with a target CPA uses device bid adjustments.
    target_cpa: bool = False
    # Each `targetingDimension` with its `bidOnly`, sorted, as `restrictions` returns them.
    restrictions: tuple[Mapping[str, Any], ...] = ()
    # The ad group's campaign; None for a campaign.
    campaign_id: str | None = None
    campaign_name: str | None = None
    campaign_status: str | None = None

    def ignores_device_bids(self) -> bool:
        strategy = self.bidding_strategy
        return strategy in _IGNORE_DEVICE_BIDS or (
            strategy == "MAXIMIZE_CONVERSIONS" and not self.target_cpa
        )

    def ignores_smart_bidding_adjustments(self) -> bool:
        return self.bidding_strategy in _SMART_BIDDING

    def audience_mode(self) -> str | None:
        """OBSERVATION, TARGETING, or None when Google's default applies."""
        for item in self.restrictions:
            if item["targetingDimension"] == "AUDIENCE":
                return "OBSERVATION" if item["bidOnly"] else "TARGETING"
        return None

    def values(self) -> dict[str, dict[str, Any]]:
        """Returns this campaign's or ad group's live values by edit key, for the edit seam."""
        values: dict[str, dict[str, Any]] = {
            self.resource_name: {
                _SETTING_PATH: self.location_setting,
                RESTRICTIONS_PATH: [dict(item) for item in self.restrictions],
            }
        }
        for key, criterion in self.criteria.items():
            values[key] = {"resourceName": criterion.resource_name}
            values[criterion.resource_name] = {BID_MODIFIER_PATH: criterion.bid_modifier}
        return values


def criterion_key(owner: str, kind: CriterionKind, value: str) -> str:
    """Names a criterion on its owner; an included and an excluded value have different keys."""
    return f"{owner}/{kind}/{value}"


def radius_value(latitude_micro: int, longitude_micro: int, radius: float, units: str) -> str:
    return f"{latitude_micro},{longitude_micro},{radius:g},{units}"


def schedule_value(day: str, start: str, end: str) -> str:
    """Names one weekly window, such as `MONDAY,07:00,22:00`."""
    return f"{day},{start},{end}"


def audience_value(kind: str, key: str) -> str:
    """Names one audience, such as `user_interest:80432`."""
    return f"{kind}:{key}"


def demographic_value(dimension: str, value: str) -> str:
    """Names one demographic value, such as `AGE_RANGE:AGE_RANGE_18_24`."""
    return f"{dimension}:{value}"


def restrictions(setting: Any) -> tuple[dict[str, Any], ...]:
    """Normalises Google's `targetingSetting` to sorted dimensions with an explicit `bidOnly`."""
    items = setting.get("targetRestrictions") if isinstance(setting, Mapping) else None
    found = {
        str(item["targetingDimension"]): bool(item.get("bidOnly"))
        for item in (items if isinstance(items, list) else ())
        if isinstance(item, Mapping) and item.get("targetingDimension")
    }
    return tuple(
        {"targetingDimension": dimension, "bidOnly": bid_only}
        for dimension, bid_only in sorted(found.items())
    )


def _clock(hour: Any, minute: Any) -> str | None:
    minutes = _MINUTES.get(str(minute or "ZERO"))
    if minutes is None or not isinstance(hour, int | str) or not str(hour).isdigit():
        return None
    return f"{int(hour):02d}:{minutes:02d}"


def _audience(row: Mapping[str, Any], common: dict[str, Any]) -> LiveCriterion | None:
    # Excluded audiences aren't changed here, so they're left out.
    kind = _AUDIENCE_TYPES[str(row.get("type"))]
    field, name_field, _collection = AUDIENCE_FIELDS[kind]
    key = str((row.get(field) or {}).get(name_field, "")).rpartition("/")[2]
    if row.get("negative") or not key.isdigit():
        return None
    return LiveCriterion(kind="audience", value=audience_value(kind, key), **common)


def _demographic(row: Mapping[str, Any], common: dict[str, Any]) -> LiveCriterion | None:
    dimension = str(row.get("type"))
    value = (row.get(DEMOGRAPHIC_FIELDS[dimension]) or {}).get("type")
    if not isinstance(value, str) or not value:
        return None
    kind: CriterionKind = "excluded_demographic" if row.get("negative") else "demographic"
    return LiveCriterion(kind=kind, value=demographic_value(dimension, value), **common)


def _live_criterion(row: Mapping[str, Any]) -> LiveCriterion | None:
    resource_name = row.get("resourceName")
    criterion_id = str(row.get("criterionId", ""))
    if not isinstance(resource_name, str) or not criterion_id.isdigit():
        return None
    # Google leaves the modifier out, or sends zero, when no adjustment is set.
    modifier = round(float(row.get("bidModifier") or 1.0), 2)
    common: dict[str, Any] = {
        "resource_name": resource_name,
        "criterion_id": criterion_id,
        "bid_modifier": modifier,
    }
    criterion_type = row.get("type")
    if criterion_type in _AUDIENCE_TYPES:
        return _audience(row, common)
    if criterion_type in DEMOGRAPHIC_FIELDS:
        return _demographic(row, common)
    if criterion_type == "LOCATION":
        location = row.get("location") or {}
        key = str(location.get("geoTargetConstant", "")).rpartition("/")[2]
        kind: CriterionKind = "excluded_location" if row.get("negative") else "location"
        return LiveCriterion(kind=kind, value=key, **common) if key.isdigit() else None
    if criterion_type == "LANGUAGE":
        language = row.get("language") or {}
        key = str(language.get("languageConstant", "")).rpartition("/")[2]
        return LiveCriterion(kind="language", value=key, **common) if key.isdigit() else None
    if criterion_type == "DEVICE":
        device = str((row.get("device") or {}).get("type", ""))
        # A device's modifier of zero excludes it, so only a missing one means no adjustment.
        raw = row.get("bidModifier")
        common["bid_modifier"] = 1.0 if raw is None else round(float(raw), 2)
        return LiveCriterion(kind="device", value=device, **common) if device else None
    if criterion_type == "AD_SCHEDULE":
        schedule = row.get("adSchedule") or {}
        day = schedule.get("dayOfWeek")
        start = _clock(schedule.get("startHour", 0), schedule.get("startMinute"))
        end = _clock(schedule.get("endHour", 0), schedule.get("endMinute"))
        if not isinstance(day, str) or start is None or end is None:
            return None
        return LiveCriterion(kind="schedule", value=schedule_value(day, start, end), **common)
    if criterion_type == "PROXIMITY":
        return _radius(row, common)
    return None


def _radius(row: Mapping[str, Any], common: dict[str, Any]) -> LiveCriterion | None:
    proximity = row.get("proximity") or {}
    point = proximity.get("geoPoint") or {}
    latitude = point.get("latitudeInMicroDegrees")
    longitude = point.get("longitudeInMicroDegrees")
    radius = proximity.get("radius")
    units = proximity.get("radiusUnits") or "KILOMETERS"
    if latitude is None or longitude is None or radius is None:
        return None
    return LiveCriterion(
        kind="radius",
        value=radius_value(int(latitude), int(longitude), float(radius), units),
        latitude_micro=int(latitude),
        longitude_micro=int(longitude),
        radius=float(radius),
        units=units,
        **common,
    )


async def read_targeting(
    client: GoogleAdsClient,
    *,
    customer_id: str,
    login_customer_id: str,
    campaign_ids: Sequence[str] = (),
    ad_group_ids: Sequence[str] = (),
    types: Sequence[CriterionType],
) -> dict[str, LiveTargeting]:
    """Returns each campaign and ad group that exists, removed ones included, by resource name,
    with its criteria of the types.

    Raises:
        IntegrationValidationError: When they hold too many criteria to compare.
    """
    if any(not item.isdigit() for item in (*campaign_ids, *ad_group_ids)):
        raise ValueError("Google Ads campaign and ad group ids must contain only digits")
    customer = normalize_customer_id(customer_id)
    live: dict[str, LiveTargeting] = {}
    if campaign_ids:
        live.update(await _read_campaigns(client, customer, login_customer_id, campaign_ids, types))
    ad_group_types = [item for item in types if item in AD_GROUP_TYPES]
    if ad_group_ids and ad_group_types:
        live.update(
            await _read_ad_groups(client, customer, login_customer_id, ad_group_ids, ad_group_types)
        )
    return live


async def _read_criteria(
    client: GoogleAdsClient,
    customer: str,
    login_customer_id: str,
    *,
    level: Literal["campaign", "ad_group"],
    ids: Sequence[str],
    types: Sequence[CriterionType],
) -> dict[str, dict[str, LiveCriterion]]:
    """Returns each owner's criteria by `criterion_key`, keyed by the owner's resource name."""
    resource = f"{level}_criterion"
    fields = (*_COMMON_FIELDS, *(_CAMPAIGN_ONLY_FIELDS if level == "campaign" else ()))
    selected = ", ".join(f"{resource}.{field}" for field in (*fields, *_SHARED_FIELDS))
    payload = await client.post(
        f"customers/{customer}/googleAds:searchStream",
        operation=f"read_{level}_criteria",
        policy=IntegrationRequestPolicy.READ,
        login_customer_id=login_customer_id,
        json={
            "query": (
                f"SELECT {level}.id, {selected} FROM {resource} "  # noqa: S608 -- digit-only ids and fixed types
                f"WHERE {level}.id IN ({', '.join(sorted(set(ids)))}) "
                f"AND {resource}.type IN ({', '.join(f"'{item}'" for item in types)}) "
                f"AND {resource}.status != 'REMOVED'"
            )
        },
    )
    rows = stream_rows(payload, max_rows=_MAX_CRITERIA)
    if len(rows) >= _MAX_CRITERIA:
        raise IntegrationValidationError(
            "These campaigns hold too many targeting settings to check at once. Change fewer "
            "campaigns.",
            provider_key="google_ads",
            failure_disposition=IntegrationFailureDisposition.NOT_DISPATCHED,
        )
    collection = "campaigns" if level == "campaign" else "adGroups"
    row_key = "campaignCriterion" if level == "campaign" else "adGroupCriterion"
    owner_key = "campaign" if level == "campaign" else "adGroup"
    by_owner: dict[str, dict[str, LiveCriterion]] = {}
    for row in rows:
        criterion = _live_criterion(row.get(row_key) or {})
        owner_id = str((row.get(owner_key) or {}).get("id", ""))
        if criterion is not None:
            owner = f"customers/{customer}/{collection}/{owner_id}"
            key = criterion_key(owner, criterion.kind, criterion.value)
            by_owner.setdefault(owner, {})[key] = criterion
    return by_owner


async def _read_campaigns(
    client: GoogleAdsClient,
    customer: str,
    login_customer_id: str,
    campaign_ids: Sequence[str],
    types: Sequence[CriterionType],
) -> dict[str, LiveTargeting]:
    campaigns = await client.post(
        f"customers/{customer}/googleAds:searchStream",
        operation="read_campaign_targeting",
        policy=IntegrationRequestPolicy.READ,
        login_customer_id=login_customer_id,
        json={
            "query": (
                "SELECT campaign.id, campaign.name, campaign.status, "  # noqa: S608 -- digit-only ids
                "campaign.advertising_channel_type, campaign.bidding_strategy_type, "
                "campaign.maximize_conversions.target_cpa_micros, "
                "bidding_strategy.maximize_conversions.target_cpa_micros, "
                "campaign.geo_target_type_setting.positive_geo_target_type, "
                "campaign.targeting_setting.target_restrictions "
                f"FROM campaign WHERE campaign.id IN ({', '.join(sorted(set(campaign_ids)))})"
            )
        },
    )
    criteria = await _read_criteria(
        client, customer, login_customer_id, level="campaign", ids=campaign_ids, types=types
    )
    live: dict[str, LiveTargeting] = {}
    for row in stream_rows(campaigns, max_rows=len(campaign_ids)):
        campaign = row.get("campaign") or {}
        owner = f"customers/{customer}/campaigns/{campaign.get('id', '')}"
        setting = campaign.get("geoTargetTypeSetting") or {}
        live[owner] = LiveTargeting(
            resource_name=owner,
            name=str(campaign.get("name") or campaign.get("id", "")),
            status=str(campaign.get("status") or "UNKNOWN"),
            channel=str(campaign.get("advertisingChannelType") or "UNKNOWN"),
            location_setting=setting.get("positiveGeoTargetType"),
            criteria=criteria.get(owner, {}),
            bidding_strategy=campaign.get("biddingStrategyType"),
            target_cpa=_target_cpa(campaign) or _target_cpa(row.get("biddingStrategy")),
            restrictions=restrictions(campaign.get("targetingSetting")),
        )
    return live


async def _read_ad_groups(
    client: GoogleAdsClient,
    customer: str,
    login_customer_id: str,
    ad_group_ids: Sequence[str],
    types: Sequence[CriterionType],
) -> dict[str, LiveTargeting]:
    ad_groups = await client.post(
        f"customers/{customer}/googleAds:searchStream",
        operation="read_ad_group_targeting",
        policy=IntegrationRequestPolicy.READ,
        login_customer_id=login_customer_id,
        json={
            "query": (
                "SELECT ad_group.id, ad_group.name, ad_group.status, "  # noqa: S608 -- digit-only ids
                "ad_group.targeting_setting.target_restrictions, campaign.id, campaign.name, "
                "campaign.status, campaign.advertising_channel_type, "
                "campaign.bidding_strategy_type "
                f"FROM ad_group WHERE ad_group.id IN ({', '.join(sorted(set(ad_group_ids)))})"
            )
        },
    )
    criteria = await _read_criteria(
        client, customer, login_customer_id, level="ad_group", ids=ad_group_ids, types=types
    )
    live: dict[str, LiveTargeting] = {}
    for row in stream_rows(ad_groups, max_rows=len(ad_group_ids)):
        ad_group = row.get("adGroup") or {}
        campaign = row.get("campaign") or {}
        owner = f"customers/{customer}/adGroups/{ad_group.get('id', '')}"
        live[owner] = LiveTargeting(
            resource_name=owner,
            name=str(ad_group.get("name") or ad_group.get("id", "")),
            status=str(ad_group.get("status") or "UNKNOWN"),
            channel=str(campaign.get("advertisingChannelType") or "UNKNOWN"),
            location_setting=None,
            criteria=criteria.get(owner, {}),
            bidding_strategy=campaign.get("biddingStrategyType"),
            restrictions=restrictions(ad_group.get("targetingSetting")),
            campaign_id=str(campaign.get("id", "")) or None,
            campaign_name=campaign.get("name"),
            campaign_status=campaign.get("status"),
        )
    return live


def _target_cpa(value: Any) -> bool:
    if not isinstance(value, Mapping):
        return False
    micros = (value.get("maximizeConversions") or {}).get("targetCpaMicros")
    return str(micros or "").isdigit() and int(micros) > 0
