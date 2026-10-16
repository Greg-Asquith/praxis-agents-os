# apps/api/integrations/meta_ads/operations/list_objects.py

"""Read account-scoped advertising objects with bounded filters and paging."""

import json
from collections.abc import Sequence
from decimal import Decimal
from typing import Any

from pydantic import TypeAdapter, ValidationError

from services.integrations.report_results import ReportResultBudget, report_result_max_bytes

from ..client import MetaAdsClient, ad_account_path
from ..models import (
    MetaAdsId,
    MetaAdsObjectBudget,
    MetaAdsPlacements,
    MetaAdsPromotedObject,
)
from ..tools.schemas.objects import (
    DEFAULT_STATUSES,
    OBJECT_STATUSES,
    MetaAdsObject,
    MetaAdsObjectsData,
    MetaAdsObjectsInput,
    MetaAdsObjectType,
)
from .ad_review import issue_summaries, review_reasons
from .paging import read_pages
from .values import (
    bounded_string,
    invalid_response,
    iso_datetime,
    money_value,
    require_currency,
    squashed_text,
)

_OPERATION = "list_objects"
_FIELDS = {
    "campaign": "id,name,status,effective_status,objective,daily_budget,lifetime_budget,budget_remaining,bid_strategy,start_time,stop_time,special_ad_categories,is_adset_budget_sharing_enabled,smart_promotion_type",
    "adset": "id,name,status,effective_status,campaign_id,optimization_goal,bid_amount,bid_strategy,bid_constraints,daily_budget,lifetime_budget,budget_remaining,daily_min_spend_target,daily_spend_cap,lifetime_min_spend_target,lifetime_spend_cap,start_time,end_time,destination_type,promoted_object,is_dynamic_creative,dsa_payor,dsa_beneficiary,learning_stage_info,targeting{geo_locations,publisher_platforms,facebook_positions,instagram_positions,audience_network_positions,messenger_positions,threads_positions},campaign{objective,daily_budget,lifetime_budget,special_ad_categories}",
    "ad": "id,name,status,effective_status,campaign_id,adset_id,bid_amount,ad_review_feedback,issues_info",
}
_EDGES = {"campaign": "campaigns", "adset": "adsets", "ad": "ads"}
_PLACEMENT_PLATFORMS = ("facebook", "instagram", "audience_network", "messenger", "threads")
_PROMOTED_IDS = ("page_id", "pixel_id", "application_id", "custom_conversion_id")
_SPEND_CONTROLS = {
    "min_daily_spend": "daily_min_spend_target",
    "max_daily_spend": "daily_spend_cap",
    "min_lifetime_spend": "lifetime_min_spend_target",
    "max_lifetime_spend": "lifetime_spend_cap",
}
# Meta's value for a spend cap that isn't set, in minor units.
NO_SPEND_CAP = 922337203685478


async def list_objects(
    client: MetaAdsClient,
    *,
    account_id: str,
    object_type: MetaAdsObjectType,
    object_ids: Sequence[str] = (),
    statuses: list[str] | None = None,
    campaign_ids: list[str] | None = None,
    adset_ids: list[str] | None = None,
    name_contains: str | None = None,
    limit: int = 100,
    currency: str,
    max_response_bytes: int | None = None,
) -> MetaAdsObjectsData:
    try:
        request = MetaAdsObjectsInput(
            object_type=object_type,
            statuses=statuses,
            campaign_ids=campaign_ids,
            adset_ids=adset_ids,
            name_contains=name_contains,
            limit=limit,
        )
        ids = TypeAdapter(list[MetaAdsId]).validate_python(list(object_ids))
        if len(ids) > 50:
            raise ValueError("Too many object IDs.")
    except (ValidationError, ValueError):
        raise invalid_response(
            "Meta Ads object filters are invalid.", operation=_OPERATION
        ) from None
    require_currency(currency, operation=_OPERATION)
    budget = ReportResultBudget(
        "meta_ads",
        _OPERATION,
        maximum=max_response_bytes if max_response_bytes is not None else report_result_max_bytes(),
    )
    rows, truncated = await read_pages(
        client,
        path=f"{ad_account_path(account_id)}/{_EDGES[object_type]}",
        account_id=account_id,
        params={
            "fields": _FIELDS[object_type],
            "filtering": json.dumps(_filters(request, ids)),
        },
        limit=limit,
        budget=budget,
        operation=_OPERATION,
    )
    try:
        objects = [
            _object(row, object_type, currency) for row in rows if not ids or row.get("id") in ids
        ]
        return MetaAdsObjectsData(
            object_type=object_type,
            objects=objects,
            object_count=len(objects),
            truncated=truncated,
            currency=currency,
        )
    except ValidationError:
        raise invalid_response(
            "Meta Ads returned an invalid advertising object.", operation=_OPERATION
        ) from None


def _filters(request: MetaAdsObjectsInput, ids: list[str]) -> list[dict[str, Any]]:
    statuses = request.statuses or (
        list(OBJECT_STATUSES[request.object_type]) if ids else DEFAULT_STATUSES[request.object_type]
    )
    filters: list[dict[str, Any]] = [
        {"field": "effective_status", "operator": "IN", "value": statuses}
    ]
    for field, values in (
        ("id", ids),
        ("campaign.id", request.campaign_ids),
        ("adset.id", request.adset_ids),
    ):
        if values:
            filters.append({"field": field, "operator": "IN", "value": values})
    if request.name_contains is not None:
        filters.append({"field": "name", "operator": "CONTAIN", "value": request.name_contains})
    return filters


def _object(raw: dict[str, Any], object_type: MetaAdsObjectType, currency: str) -> MetaAdsObject:
    values = {
        field: bounded_string(raw.get(field), operation=_OPERATION)
        for field in (
            "name",
            "status",
            "effective_status",
            "objective",
            "optimization_goal",
            "bid_strategy",
            "destination_type",
        )
    }
    campaign = _mapping(raw.get("campaign"))
    if object_type == "adset":
        values["objective"] = bounded_string(campaign.get("objective"), operation=_OPERATION)
    end_field = "stop_time" if object_type == "campaign" else "end_time"
    return MetaAdsObject(
        id=raw.get("id"),
        **values,
        start_time=iso_datetime(raw.get("start_time"), operation=_OPERATION),
        end_time=iso_datetime(raw.get(end_field), operation=_OPERATION),
        campaign_id=raw.get("campaign_id"),
        adset_id=raw.get("adset_id"),
        bid_amount=money_value(raw.get("bid_amount"), currency, operation=_OPERATION),
        budget=_budget(raw, object_type, currency),
        promoted_object=_promoted_object(raw.get("promoted_object")),
        placements=_placements(raw.get("targeting")) if object_type == "adset" else None,
        is_dynamic_creative=raw.get("is_dynamic_creative"),
        special_ad_categories=_categories(
            (campaign if object_type == "adset" else raw).get("special_ad_categories")
        )
        if object_type != "ad"
        else None,
        share_between_ad_sets=raw.get("is_adset_budget_sharing_enabled")
        if object_type == "campaign"
        else None,
        review_reasons=review_reasons(raw) if object_type == "ad" else None,
        issues=issue_summaries(raw) if object_type == "ad" else None,
        smart_promotion_type=bounded_string(raw.get("smart_promotion_type"), operation=_OPERATION)
        if object_type == "campaign"
        else None,
        **(_ad_set_settings(raw, currency) if object_type == "adset" else {}),
    )


def _ad_set_settings(raw: dict[str, Any], currency: str) -> dict[str, Any]:
    """Reads the ad set settings that edits change, beyond those every object has."""
    floor = _mapping(raw.get("bid_constraints")).get("roas_average_floor")
    learning = _mapping(raw.get("learning_stage_info"))
    targeting = raw.get("targeting")
    return {
        "min_roas": _ratio(floor),
        **{key: _spend_control(raw.get(field), currency) for key, field in _SPEND_CONTROLS.items()},
        "eu_payer": squashed_text(raw.get("dsa_payor"), 512),
        "eu_beneficiary": squashed_text(raw.get("dsa_beneficiary"), 512),
        "learning_status": bounded_string(learning.get("status"), operation=_OPERATION),
        "countries": _countries(targeting) if isinstance(targeting, dict) else None,
    }


def _ratio(floor: Any) -> str | None:
    """Turns Meta's return floor, the ratio times 10,000, back into the ratio."""
    if floor is None:
        return None
    if isinstance(floor, bool) or not isinstance(floor, (int, str)) or not str(floor).isdigit():
        raise invalid_response("Meta Ads returned an invalid return goal.", operation=_OPERATION)
    return format((Decimal(int(floor)) / 10_000).normalize(), "f")


def _spend_control(value: Any, currency: str) -> str | None:
    """Returns None for a control that isn't set, which Meta shows as empty, zero, or no cap."""
    if value in (None, "", "0", 0) or str(value) == str(NO_SPEND_CAP):
        return None
    return money_value(value, currency, operation=_OPERATION)


def _countries(targeting: dict[str, Any]) -> list[str]:
    """Lists the countries of every place the ad set reaches, for rules such as the EU's."""
    geo = _mapping(targeting.get("geo_locations"))
    countries = [item for item in geo.get("countries") or [] if isinstance(item, str)]
    for key in ("regions", "cities", "zips", "geo_markets", "custom_locations"):
        for place in geo.get(key) or []:
            country = _mapping(place).get("country")
            if isinstance(country, str):
                countries.append(country)
    return sorted({item for item in countries if len(item) == 2 and item.isupper()})[:300]


def _held_budget(raw: dict[str, Any], currency: str) -> tuple[str, str] | None:
    for kind in ("daily", "lifetime"):
        amount = money_value(raw.get(f"{kind}_budget"), currency, operation=_OPERATION)
        if amount is not None and Decimal(amount) != 0:
            return kind, amount
    return None


def _budget(
    raw: dict[str, Any], object_type: MetaAdsObjectType, currency: str
) -> MetaAdsObjectBudget | None:
    if object_type == "ad":
        return None
    remaining = money_value(raw.get("budget_remaining"), currency, operation=_OPERATION)
    if held := _held_budget(raw, currency):
        return MetaAdsObjectBudget(kind=held[0], amount=held[1], remaining=remaining)
    # An ad set without its own budget uses the campaign's only when the campaign shows one.
    if object_type == "adset" and (
        campaign := _held_budget(_mapping(raw.get("campaign")), currency)
    ):
        return MetaAdsObjectBudget(
            kind="campaign", amount=campaign[1], remaining=remaining, period=campaign[0]
        )
    return None


def _promoted_object(value: Any) -> MetaAdsPromotedObject | None:
    raw = _mapping(value)
    if not raw:
        return None
    ids = {key: str(raw[key]) for key in _PROMOTED_IDS if raw.get(key) is not None}
    return MetaAdsPromotedObject(
        **ids,
        custom_event_type=bounded_string(raw.get("custom_event_type"), operation=_OPERATION),
    )


def _placements(targeting: Any) -> MetaAdsPlacements | None:
    """Returns None when Meta sent no targeting, since placements are then unknown."""
    if targeting is None:
        return None
    if not isinstance(targeting, dict):
        raise invalid_response("Meta Ads returned invalid placements.", operation=_OPERATION)
    platforms = targeting.get("publisher_platforms")
    # Targeting without publisher platforms uses Meta's automatic placements.
    if platforms is None or platforms == []:
        return MetaAdsPlacements(mode="automatic")
    if not isinstance(platforms, list):
        raise invalid_response("Meta Ads returned invalid placements.", operation=_OPERATION)
    positions: list[str] = []
    for platform in platforms:
        if platform not in _PLACEMENT_PLATFORMS:
            raise invalid_response("Meta Ads returned invalid placements.", operation=_OPERATION)
        named = targeting.get(f"{platform}_positions") or []
        if not isinstance(named, list) or any(not isinstance(item, str) for item in named):
            raise invalid_response("Meta Ads returned invalid placements.", operation=_OPERATION)
        positions.extend([f"{platform}:{item}" for item in named] or [platform])
    return MetaAdsPlacements(mode="manual", positions=positions)


def _categories(value: Any) -> list[str] | None:
    if value is None:
        return None
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise invalid_response("Meta Ads returned invalid ad categories.", operation=_OPERATION)
    return value[:8]


def _mapping(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


async def read_objects_by_id(
    client: MetaAdsClient,
    *,
    account_id: str,
    object_type: MetaAdsObjectType,
    object_ids: Sequence[str],
    currency: str,
) -> dict[str, MetaAdsObject]:
    """Returns the requested objects that the account's own edge still lists, in any status."""
    ids = sorted(set(object_ids))
    found: dict[str, MetaAdsObject] = {}
    for start in range(0, len(ids), 50):
        chunk = ids[start : start + 50]
        result = await list_objects(
            client,
            account_id=account_id,
            object_type=object_type,
            object_ids=chunk,
            limit=len(chunk),
            currency=currency,
        )
        found.update((item.id, item) for item in result.objects)
    return found
