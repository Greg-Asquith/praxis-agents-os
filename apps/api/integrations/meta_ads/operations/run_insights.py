# apps/api/integrations/meta_ads/operations/run_insights.py

"""Read bounded Meta Insights reports, including background fallback."""

import asyncio
import json
import re
import time
from datetime import UTC, date, datetime
from typing import Any, Literal

from core.exceptions.integration import IntegrationValidationError
from services.integrations.http import IntegrationRequestPolicy
from services.integrations.report_results import ReportResultBudget, report_result_max_bytes

from ..client import MetaAdsClient, ad_account_path
from ..insights_fields import (
    ACTION_FIELDS,
    COUNT_FIELDS,
    MONEY_FIELDS,
    RETAINED_METRICS,
    TEXT_FIELDS,
)
from ..throttle import ensure_account_available
from ..tools.schemas.insights import (
    MetaAdsInsightsAction,
    MetaAdsInsightsData,
    MetaAdsInsightsInput,
    MetaAdsInsightsRow,
)
from ..tools.utils.validation import months_before
from .enrich_conversions import enrich_conversion_names
from .paging import read_pages
from .values import bounded_string, invalid_response, iso_date, numeric_value

_READ = IntegrationRequestPolicy.READ
_OPERATION = "run_insights"
# Code 100 on a submitted report is not a request the model can correct.
_REPORT_OPERATION = "read_insights_report"
_PAGE_SIZE = 1000
_NARROW_REPORT = "Narrow the date range, level, or breakdowns and try again."


async def run_insights(
    client: MetaAdsClient,
    *,
    account_id: str,
    request: MetaAdsInsightsInput,
    max_rows: int,
    poll_seconds: float,
    max_response_bytes: int | None = None,
) -> MetaAdsInsightsData:
    limit = min(request.limit, max_rows)
    if limit < 1 or poll_seconds <= 0:
        raise invalid_response("Meta Ads report limits must be positive.", operation=_OPERATION)
    budget = ReportResultBudget(
        "meta_ads",
        _OPERATION,
        maximum=max_response_bytes if max_response_bytes is not None else report_result_max_bytes(),
    )
    params, fields, notes = _parameters(request, limit)
    path = f"{ad_account_path(account_id)}/insights"
    mode: Literal["direct", "background"] = "direct"
    try:
        rows, truncated = await _read_rows(
            client, path, params, account_id, limit, budget, operation=_OPERATION
        )
    except IntegrationValidationError as exc:
        if exc.error_code != "meta_ads_insights_too_large":
            raise
        mode = "background"
        job_path = await _background_report(client, path, params, account_id, poll_seconds, budget)
        rows, truncated = await _read_rows(
            client, job_path, {}, account_id, limit, budget, operation=_REPORT_OPERATION
        )
    typed_rows = [_row(row, request, fields) for row in rows]
    notes.extend(
        await enrich_conversion_names(client, account_id=account_id, rows=typed_rows, budget=budget)
    )
    return MetaAdsInsightsData(
        rows=typed_rows,
        row_count=len(rows),
        truncated=truncated,
        truncation_note=f"The report reached its {limit}-row or pagination limit."
        if truncated
        else None,
        mode=mode,
        notes=notes,
        money_fields=sorted(MONEY_FIELDS.intersection(fields)),
        level=request.level,
        since=request.since,
        until=request.until,
    )


def _identity_fields(level: str) -> list[str]:
    levels = ["account", "campaign", "adset", "ad"]
    return [
        f"{item}_{suffix}"
        for item in levels[: levels.index(level) + 1]
        for suffix in ("id", "name")
    ]


def _parameters(
    request: MetaAdsInsightsInput, limit: int
) -> tuple[dict[str, Any], list[str], list[str]]:
    fields = list(dict.fromkeys(request.fields))
    notes = []
    if request.breakdowns and date.fromisoformat(request.since) < months_before(
        datetime.now(UTC).date(), 13
    ):
        removed = [field for field in fields if field in RETAINED_METRICS]
        fields = [field for field in fields if field not in RETAINED_METRICS]
        if removed:
            notes.append(
                f"Meta omits {', '.join(removed)} with breakdowns beyond 13 months; these fields were removed."
            )
    params: dict[str, Any] = {
        "fields": ",".join(
            dict.fromkeys(
                [
                    *fields,
                    *_identity_fields(request.level),
                    "date_start",
                    "date_stop",
                    "account_currency",
                ]
            )
        ),
        "level": request.level,
        "time_range": json.dumps({"since": request.since, "until": request.until}),
        "time_increment": request.time_increment,
        "limit": min(limit, _PAGE_SIZE),
    }
    if request.breakdowns:
        params["breakdowns"] = ",".join(request.breakdowns)
    if ACTION_FIELDS.intersection(fields):
        params["action_breakdowns"] = ",".join(request.action_breakdowns or ["action_type"])
    if request.attribution_windows:
        params["action_attribution_windows"] = json.dumps(request.attribution_windows)
        notes.append("Attribution windows override each ad set's attribution setting.")
    else:
        params["use_unified_attribution_setting"] = "true"
    if request.filters:
        params["filtering"] = json.dumps([item.model_dump() for item in request.filters])
    if request.sort:
        params["sort"] = json.dumps([request.sort])
    return params, fields, notes


async def _read_rows(
    client: MetaAdsClient,
    path: str,
    params: dict[str, Any],
    account_id: str,
    limit: int,
    budget: ReportResultBudget,
    *,
    operation: str,
) -> tuple[list[dict[str, Any]], bool]:
    # Each non-final page holds at least one row, so the limit bounds the page count.
    return await read_pages(
        client,
        path=path,
        account_id=account_id,
        params=params,
        limit=limit,
        budget=budget,
        operation=operation,
        page_size=_PAGE_SIZE,
        max_pages=limit,
    )


async def _background_report(
    client: MetaAdsClient,
    path: str,
    params: dict[str, Any],
    account_id: str,
    poll_seconds: float,
    budget: ReportResultBudget,
) -> str:
    ensure_account_available(account_id, operation=_OPERATION)
    payload = await client.graph_post(
        path,
        data=params,
        operation=_OPERATION,
        policy=_READ,
        max_response_bytes=budget.remaining,
    )
    budget.add(payload)
    report_id = payload.get("report_run_id")
    if not isinstance(report_id, str) or not re.fullmatch(r"[0-9]+", report_id):
        raise invalid_response(
            "Meta Ads returned an invalid background report.", operation=_OPERATION
        )
    deadline = time.monotonic() + poll_seconds
    delay = 1
    while (remaining := deadline - time.monotonic()) > 0:
        try:
            async with asyncio.timeout(remaining):
                ensure_account_available(account_id, operation=_OPERATION)
                status = await client.graph_get(
                    report_id,
                    params={"fields": "async_status,async_percent_completion"},
                    operation=_REPORT_OPERATION,
                    policy=_READ,
                    max_response_bytes=budget.remaining,
                    usage_account_id=account_id,
                )
        except TimeoutError:
            break
        budget.add(status)
        state = status.get("async_status")
        if state in {"Job Failed", "Job Skipped"}:
            raise invalid_response(
                f"Meta Ads could not complete the background report. {_NARROW_REPORT}",
                operation=_OPERATION,
            )
        if (
            state == "Job Completed"
            and numeric_value(status.get("async_percent_completion"), operation=_OPERATION) == 100
        ):
            return f"{report_id}/insights"
        await asyncio.sleep(min(delay, max(0, deadline - time.monotonic())))
        delay = min(delay * 2, 5)
    raise invalid_response(
        f"Meta Ads did not complete the background report in time. {_NARROW_REPORT}",
        operation=_OPERATION,
    )


def _row(
    raw: dict[str, Any], request: MetaAdsInsightsInput, fields: list[str]
) -> MetaAdsInsightsRow:
    key_fields = (
        set(_identity_fields(request.level))
        | set(request.breakdowns)
        | (TEXT_FIELDS.intersection(fields) - {"date_start", "date_stop"})
    )
    keys = {
        field: bounded_string(raw.get(field), operation=_OPERATION) for field in sorted(key_fields)
    }
    metrics: dict[str, int | float | None] = {}
    actions: dict[str, list[MetaAdsInsightsAction]] = {}
    for field in fields:
        if field in key_fields or field in {"date_start", "date_stop", "account_currency"}:
            continue
        value = raw.get(field)
        if field in ACTION_FIELDS:
            actions[field] = _actions(value, request)
        else:
            metrics[field] = numeric_value(value, count=field in COUNT_FIELDS, operation=_OPERATION)
    return MetaAdsInsightsRow(
        keys=keys,
        metrics=metrics,
        actions=actions,
        date_start=iso_date(raw.get("date_start"), operation=_OPERATION),
        date_stop=iso_date(raw.get("date_stop"), operation=_OPERATION),
    )


def _actions(value: Any, request: MetaAdsInsightsInput) -> list[MetaAdsInsightsAction]:
    if value is None:
        return []
    if not isinstance(value, list) or len(value) > 1000:
        raise invalid_response("Meta Ads returned invalid action values.", operation=_OPERATION)
    result = []
    for item in value:
        if not isinstance(item, dict) or not isinstance(item.get("action_type"), str):
            raise invalid_response(
                "Meta Ads returned an invalid action type.", operation=_OPERATION
            )
        result.append(
            MetaAdsInsightsAction(
                action_type=bounded_string(item["action_type"], operation=_OPERATION, maximum=256),
                value=numeric_value(item.get("value"), operation=_OPERATION),
                windows={
                    window: numeric_value(item.get(window), operation=_OPERATION)
                    for window in request.attribution_windows or []
                    if window in item
                },
                breakdowns={
                    field: bounded_string(item.get(field), operation=_OPERATION)
                    for field in request.action_breakdowns
                    if field != "action_type"
                },
            )
        )
    return result
