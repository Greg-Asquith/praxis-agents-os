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
from .paging import read_pages
from .values import bounded_string, invalid_response, iso_datetime, money_value, require_currency

_OPERATION = "list_objects"
_FIELDS = {
    "campaign": "id,name,status,effective_status,objective,daily_budget,lifetime_budget,budget_remaining,bid_strategy,start_time,stop_time",
    "adset": "id,name,status,effective_status,campaign_id,optimization_goal,bid_amount,bid_strategy,daily_budget,lifetime_budget,budget_remaining,start_time,end_time,destination_type,promoted_object,is_dynamic_creative,targeting{publisher_platforms,facebook_positions,instagram_positions,audience_network_positions,messenger_positions,threads_positions},campaign{objective,daily_budget,lifetime_budget}",
    "ad": "id,name,status,effective_status,campaign_id,adset_id",
}
_EDGES = {"campaign": "campaigns", "adset": "adsets", "ad": "ads"}
_PLACEMENT_PLATFORMS = ("facebook", "instagram", "audience_network", "messenger", "threads")
_PROMOTED_IDS = ("page_id", "pixel_id", "application_id", "custom_conversion_id")


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
    )


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
