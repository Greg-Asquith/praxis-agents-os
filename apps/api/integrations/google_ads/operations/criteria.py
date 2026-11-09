# apps/api/integrations/google_ads/operations/criteria.py

"""Reads campaign criteria by type, as the live values the edit seam compares against."""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Literal

from core.exceptions.integration import IntegrationFailureDisposition, IntegrationValidationError
from services.integrations.http import IntegrationRequestPolicy

from ..client import GoogleAdsClient, normalize_customer_id
from .utils import stream_rows

type CriterionKind = Literal["location", "excluded_location", "radius", "language"]
type CriterionType = Literal["LOCATION", "PROXIMITY", "LANGUAGE"]

# Google allows 10,000 locations a campaign, so this only stops an unbounded read.
_MAX_CRITERIA = 50_000
_SETTING_PATH = "geoTargetTypeSetting.positiveGeoTargetType"
BID_MODIFIER_PATH = "bidModifier"


@dataclass(frozen=True, slots=True)
class LiveCriterion:
    kind: CriterionKind
    # The location or language key, or a radius's identity from `radius_value`.
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
class LiveCampaignTargeting:
    resource_name: str
    name: str
    status: str
    channel: str
    location_setting: str | None
    # By `criterion_key`.
    criteria: Mapping[str, LiveCriterion]

    def values(self) -> dict[str, dict[str, Any]]:
        """Returns this campaign's live values by edit key, for the edit seam."""
        values: dict[str, dict[str, Any]] = {
            self.resource_name: {_SETTING_PATH: self.location_setting}
        }
        for key, criterion in self.criteria.items():
            values[key] = {"resourceName": criterion.resource_name}
            values[criterion.resource_name] = {BID_MODIFIER_PATH: criterion.bid_modifier}
        return values


def criterion_key(campaign: str, kind: CriterionKind, value: str) -> str:
    """Names a criterion on its campaign; an included and an excluded place have different keys."""
    return f"{campaign}/{kind}/{value}"


def radius_value(latitude_micro: int, longitude_micro: int, radius: float, units: str) -> str:
    return f"{latitude_micro},{longitude_micro},{radius:g},{units}"


def _live_criterion(row: Mapping[str, Any]) -> LiveCriterion | None:
    resource_name = row.get("resourceName")
    criterion_id = str(row.get("criterionId", ""))
    if not isinstance(resource_name, str) or not criterion_id.isdigit():
        return None
    # Google leaves the modifier out, or sends zero, when no adjustment is set.
    modifier = round(float(row.get("bidModifier") or 1.0), 2)
    common = {
        "resource_name": resource_name,
        "criterion_id": criterion_id,
        "bid_modifier": modifier,
    }
    criterion_type = row.get("type")
    if criterion_type == "LOCATION":
        location = row.get("location") or {}
        key = str(location.get("geoTargetConstant", "")).rpartition("/")[2]
        kind: CriterionKind = "excluded_location" if row.get("negative") else "location"
        return LiveCriterion(kind=kind, value=key, **common) if key.isdigit() else None
    if criterion_type == "LANGUAGE":
        language = row.get("language") or {}
        key = str(language.get("languageConstant", "")).rpartition("/")[2]
        return LiveCriterion(kind="language", value=key, **common) if key.isdigit() else None
    if criterion_type == "PROXIMITY":
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
    return None


async def read_campaign_targeting(
    client: GoogleAdsClient,
    *,
    customer_id: str,
    login_customer_id: str,
    campaign_ids: Sequence[str],
    types: Sequence[CriterionType],
) -> dict[str, LiveCampaignTargeting]:
    """Returns each campaign that exists, removed ones included, with its criteria of the types.

    Raises:
        IntegrationValidationError: When the campaigns hold too many criteria to compare.
    """
    if any(not campaign_id.isdigit() for campaign_id in campaign_ids):
        raise ValueError("Google Ads campaign ids must contain only digits")
    customer = normalize_customer_id(customer_id)
    id_filter = ", ".join(sorted(set(campaign_ids)))
    type_filter = ", ".join(f"'{item}'" for item in types)
    path = f"customers/{customer}/googleAds:searchStream"
    campaigns = await client.post(
        path,
        operation="read_campaign_targeting",
        policy=IntegrationRequestPolicy.READ,
        login_customer_id=login_customer_id,
        json={
            "query": (
                "SELECT campaign.id, campaign.name, campaign.status, "  # noqa: S608 -- digit-only ids
                "campaign.advertising_channel_type, "
                "campaign.geo_target_type_setting.positive_geo_target_type "
                f"FROM campaign WHERE campaign.id IN ({id_filter})"
            )
        },
    )
    criteria = await client.post(
        path,
        operation="read_campaign_criteria",
        policy=IntegrationRequestPolicy.READ,
        login_customer_id=login_customer_id,
        json={
            "query": (
                "SELECT campaign.id, campaign_criterion.resource_name, "  # noqa: S608 -- digit-only ids and fixed types
                "campaign_criterion.criterion_id, campaign_criterion.type, "
                "campaign_criterion.negative, campaign_criterion.bid_modifier, "
                "campaign_criterion.location.geo_target_constant, "
                "campaign_criterion.language.language_constant, "
                "campaign_criterion.proximity.geo_point.latitude_in_micro_degrees, "
                "campaign_criterion.proximity.geo_point.longitude_in_micro_degrees, "
                "campaign_criterion.proximity.radius, campaign_criterion.proximity.radius_units "
                f"FROM campaign_criterion WHERE campaign.id IN ({id_filter}) "
                f"AND campaign_criterion.type IN ({type_filter}) "
                "AND campaign_criterion.status != 'REMOVED'"
            )
        },
    )
    rows = stream_rows(criteria, max_rows=_MAX_CRITERIA)
    if len(rows) >= _MAX_CRITERIA:
        raise IntegrationValidationError(
            "These campaigns hold too many locations to check at once. Change fewer campaigns.",
            provider_key="google_ads",
            failure_disposition=IntegrationFailureDisposition.NOT_DISPATCHED,
        )
    by_campaign: dict[str, dict[str, LiveCriterion]] = {}
    for row in rows:
        criterion = _live_criterion(row.get("campaignCriterion") or {})
        campaign_id = str((row.get("campaign") or {}).get("id", ""))
        if criterion is not None:
            owner = f"customers/{customer}/campaigns/{campaign_id}"
            key = criterion_key(owner, criterion.kind, criterion.value)
            by_campaign.setdefault(campaign_id, {})[key] = criterion
    live: dict[str, LiveCampaignTargeting] = {}
    for row in stream_rows(campaigns, max_rows=len(campaign_ids)):
        campaign = row.get("campaign") or {}
        campaign_id = str(campaign.get("id", ""))
        setting = campaign.get("geoTargetTypeSetting") or {}
        live[campaign_id] = LiveCampaignTargeting(
            resource_name=f"customers/{customer}/campaigns/{campaign_id}",
            name=str(campaign.get("name") or campaign_id),
            status=str(campaign.get("status") or "UNKNOWN"),
            channel=str(campaign.get("advertisingChannelType") or "UNKNOWN"),
            location_setting=setting.get("positiveGeoTargetType"),
            criteria=by_campaign.get(campaign_id, {}),
        )
    return live
