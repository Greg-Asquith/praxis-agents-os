# apps/api/integrations/meta_ads/operations/list_objects.py

"""Read account-scoped advertising objects with bounded filters and paging."""

import json
from collections.abc import Sequence
from decimal import Decimal
from typing import Any

from pydantic import TypeAdapter, ValidationError

from services.integrations.report_results import ReportResultBudget, report_result_max_bytes

from ..client import MetaAdsClient, ad_account_path
from ..tools.schemas.base import MetaAdsId
from ..tools.schemas.objects import (
    DEFAULT_STATUSES,
    OBJECT_STATUSES,
    MetaAdsObject,
    MetaAdsObjectBudget,
    MetaAdsObjectsData,
    MetaAdsObjectsInput,
    MetaAdsObjectType,
)
from .paging import read_pages
from .values import bounded_string, invalid_response, iso_datetime, money_value, require_currency

_OPERATION = "list_objects"
_FIELDS = {
    "campaign": "id,name,status,effective_status,objective,daily_budget,lifetime_budget,budget_remaining,bid_strategy,start_time,stop_time",
    "adset": "id,name,status,effective_status,campaign_id,optimization_goal,bid_amount,bid_strategy,daily_budget,lifetime_budget,budget_remaining,start_time,end_time",
    "ad": "id,name,status,effective_status,campaign_id,adset_id",
}
_EDGES = {"campaign": "campaigns", "adset": "adsets", "ad": "ads"}


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
        )
    }
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
    )


def _budget(
    raw: dict[str, Any], object_type: MetaAdsObjectType, currency: str
) -> MetaAdsObjectBudget | None:
    if object_type == "ad":
        return None
    remaining = money_value(raw.get("budget_remaining"), currency, operation=_OPERATION)
    for kind in ("daily", "lifetime"):
        amount = money_value(raw.get(f"{kind}_budget"), currency, operation=_OPERATION)
        if amount is not None and Decimal(amount) != 0:
            return MetaAdsObjectBudget(kind=kind, amount=amount, remaining=remaining)
    if object_type == "adset":
        return MetaAdsObjectBudget(kind="campaign", amount=None, remaining=remaining)
    return None
