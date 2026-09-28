# apps/api/integrations/meta_ads/operations/list_activities.py

"""Read an account's change history within a bounded date window."""

import json
from datetime import datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import ValidationError

from services.integrations.report_results import ReportResultBudget, report_result_max_bytes

from ..client import MetaAdsClient, ad_account_path
from ..tools.schemas.activities import (
    ACTIVITIES_MAX_EVENTS,
    MetaAdsActivitiesData,
    MetaAdsActivitiesInput,
    MetaAdsActivity,
)
from .paging import read_pages
from .values import bounded_string, invalid_response

_OPERATION = "list_activities"
_FIELDS = "event_type,translated_event_type,event_time,object_type,object_id,object_name,actor_name,extra_data"
_MAX_EXTRA_DATA_CHARS = 16_384
_MAX_CHANGE_VALUE_CHARS = 256
_WINDOW_NOTE = (
    "Some changes in this window may be missing because the event or page limit was reached. "
    "Narrow the dates or filter by object IDs."
)


async def list_activities(
    client: MetaAdsClient,
    *,
    account_id: str,
    request: MetaAdsActivitiesInput,
    timezone_name: str,
    max_response_bytes: int | None = None,
) -> MetaAdsActivitiesData:
    zone = _zone(timezone_name)
    start = datetime.combine(request.since, time.min, zone)
    end = datetime.combine(request.until + timedelta(days=1), time.min, zone)
    object_ids = frozenset(request.object_ids or ())
    budget = ReportResultBudget(
        "meta_ads",
        _OPERATION,
        maximum=max_response_bytes if max_response_bytes is not None else report_result_max_bytes(),
    )

    # Filter locally as well, because live window and object filtering on this edge is unverified.
    def include(row: dict[str, Any]) -> bool:
        return start <= _event_time(row.get("event_time")) < end and (
            not object_ids or row.get("object_id") in object_ids
        )

    rows, truncated = await read_pages(
        client,
        path=f"{ad_account_path(account_id)}/activities",
        account_id=account_id,
        params={
            "fields": _FIELDS,
            "since": int(start.timestamp()),
            "until": int(end.timestamp()),
        },
        limit=ACTIVITIES_MAX_EVENTS,
        budget=budget,
        operation=_OPERATION,
        include=include,
    )
    try:
        events = [_event(row) for row in rows]
        return MetaAdsActivitiesData(
            events=events,
            event_count=len(events),
            truncated=truncated,
            window_note=_WINDOW_NOTE if truncated else None,
            timezone_name=zone.key,
        )
    except ValidationError:
        raise invalid_response(
            "Meta Ads returned an invalid account activity.", operation=_OPERATION
        ) from None


def _zone(name: str) -> ZoneInfo:
    try:
        return ZoneInfo(name)
    except (ValueError, ZoneInfoNotFoundError):
        return ZoneInfo("UTC")


def _event_time(value: Any) -> datetime:
    text = bounded_string(value, operation=_OPERATION)
    try:
        parsed = datetime.fromisoformat(text) if text else None
    except ValueError:
        parsed = None
    if parsed is None or parsed.tzinfo is None:
        raise invalid_response("Meta Ads returned an invalid activity time.", operation=_OPERATION)
    return parsed


def _event(raw: dict[str, Any]) -> MetaAdsActivity:
    old_value, new_value = _changed_values(raw.get("extra_data"))
    text = {
        field: bounded_string(raw.get(field), operation=_OPERATION)
        for field in (
            "event_type",
            "translated_event_type",
            "object_type",
            "object_name",
            "actor_name",
        )
    }
    return MetaAdsActivity(
        event_time=_event_time(raw.get("event_time")).isoformat(),
        object_id=raw.get("object_id"),
        old_value=old_value,
        new_value=new_value,
        **text,
    )


def _changed_values(extra_data: Any) -> tuple[str | None, str | None]:
    """Returns scalar old and new values, dropping the rest of Meta's extra data."""
    if not isinstance(extra_data, str) or len(extra_data) > _MAX_EXTRA_DATA_CHARS:
        return None, None
    try:
        data = json.loads(extra_data)
    except (ValueError, RecursionError):
        return None, None
    if not isinstance(data, dict):
        return None, None
    return _scalar(data.get("old_value")), _scalar(data.get("new_value"))


def _scalar(value: Any) -> str | None:
    if isinstance(value, str):
        return value[:_MAX_CHANGE_VALUE_CHARS]
    if isinstance(value, (bool, int, float)):
        return json.dumps(value)[:_MAX_CHANGE_VALUE_CHARS]
    return None
