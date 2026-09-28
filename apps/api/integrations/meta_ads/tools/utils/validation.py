# apps/api/integrations/meta_ads/tools/utils/validation.py

"""Validate Meta Ads tool arguments before contacting Meta."""

import calendar
import re
from datetime import UTC, date, datetime
from typing import Any

from pydantic import ValidationError
from pydantic_ai import ModelRetry

from ...insights_fields import ACTION_FIELDS, RETAINED_METRICS, UNSUPPORTED_STRUCTURED_FIELDS
from ..schemas.insights import (
    ACTION_BREAKDOWNS,
    ATTRIBUTION_WINDOWS,
    BREAKDOWNS,
    FILTER_VALUE_KINDS,
    OBJECT_FILTERS,
    SORT_DIRECTIONS,
    MetaAdsInsightsInput,
)


def months_before(value: date, months: int) -> date:
    index = value.year * 12 + value.month - 1 - months
    if index < 12:
        return date.min
    year, month = divmod(index, 12)
    month += 1
    return date(year, month, min(value.day, calendar.monthrange(year, month)[1]))


def absolute_date(value: str, argument: str) -> date:
    try:
        parsed = date.fromisoformat(value)
    except (TypeError, ValueError):
        raise ModelRetry(f"Set {argument} to a date in YYYY-MM-DD format.") from None
    if parsed.isoformat() != value:
        raise ModelRetry(f"Set {argument} to a date in YYYY-MM-DD format.")
    return parsed


def validation_retry(exc: ValidationError) -> ModelRetry:
    """Names the first invalid argument without echoing its value."""
    error = exc.errors(include_url=False, include_input=False)[0]
    argument = ".".join(str(part) for part in error["loc"])
    message = str(error["ctx"]["error"]) if error["type"] == "value_error" else error["msg"]
    message = message.rstrip(".")
    return ModelRetry(f"Correct {argument}: {message}." if argument else f"{message}.")


def validated_insights_request(
    *, max_rows: int, today: date | None = None, **values: Any
) -> MetaAdsInsightsInput:
    try:
        request = MetaAdsInsightsInput.model_validate(values)
    except ValidationError as exc:
        raise validation_retry(exc) from None
    validate_insights_request(request, max_rows=max_rows, today=today)
    return request


def validate_insights_request(
    request: MetaAdsInsightsInput, *, max_rows: int, today: date | None = None
) -> None:
    today = today or datetime.now(UTC).date()
    _validate_fields(request)
    _validate_dates(request, today)
    _validate_breakdowns(request)
    _validate_attribution_windows(request)
    _validate_filters(request)
    if request.sort:
        field, _, direction = request.sort.rpartition("_")
        if field not in request.fields or direction not in SORT_DIRECTIONS:
            raise ModelRetry("Set sort to a requested field followed by _ascending or _descending.")
    _validate_retained_metrics(request, today)
    if request.limit > max_rows:
        raise ModelRetry(f"Set limit between 1 and {max_rows}.")


def _validate_fields(request: MetaAdsInsightsInput) -> None:
    if any(not re.fullmatch(r"[a-z0-9_]+", field) for field in request.fields):
        raise ModelRetry("Use only lowercase letters, digits, and underscores in fields.")
    unsupported = UNSUPPORTED_STRUCTURED_FIELDS.intersection(request.fields)
    if unsupported:
        raise ModelRetry(
            f"Remove unsupported structured fields: {', '.join(sorted(unsupported))}. "
            "Insights supports numeric metrics, text fields, and action statistics; "
            "generic objects and video histograms are not supported."
        )


def _validate_dates(request: MetaAdsInsightsInput, today: date) -> None:
    since = absolute_date(request.since, "since")
    until = absolute_date(request.until, "until")
    if since > until:
        raise ModelRetry("Set since on or before until.")
    if since < months_before(today, 37):
        raise ModelRetry("Set since within the past 37 months.")
    if since < months_before(today, 13) and any(
        field.startswith("unique_") for field in request.fields
    ):
        raise ModelRetry("Use a since date within the past 13 months for unique_* fields.")


def _validate_attribution_windows(request: MetaAdsInsightsInput) -> None:
    if request.attribution_windows:
        if {"7d_view", "28d_view"}.intersection(request.attribution_windows):
            raise ModelRetry(
                "Remove 7d_view and 28d_view from attribution_windows; Meta stopped returning them in January 2026."
            )
        if not set(request.attribution_windows) <= ATTRIBUTION_WINDOWS:
            raise ModelRetry(
                "Use 1d_click, 7d_click, 28d_click, 1d_view, or 1d_ev in attribution_windows."
            )


def _validate_breakdowns(request: MetaAdsInsightsInput) -> None:
    if not set(request.breakdowns) <= BREAKDOWNS:
        raise ModelRetry(
            "Use supported breakdowns: age, gender, country, region, publisher_platform, platform_position, device_platform, impression_device."
        )
    if set(request.breakdowns) == {"impression_device"}:
        raise ModelRetry("Combine impression_device with another value in breakdowns.")
    if not set(request.action_breakdowns) <= ACTION_BREAKDOWNS:
        raise ModelRetry(
            "Use action_type, action_device, or action_destination in action_breakdowns."
        )
    if request.action_breakdowns and not ACTION_FIELDS.intersection(request.fields):
        raise ModelRetry("Add an action field to fields before setting action_breakdowns.")


def _validate_retained_metrics(request: MetaAdsInsightsInput, today: date) -> None:
    if not request.breakdowns or date.fromisoformat(request.since) >= months_before(today, 13):
        return
    referenced = {item.field for item in request.filters or []}
    if request.sort:
        referenced.add(request.sort.rpartition("_")[0])
    if RETAINED_METRICS.intersection(referenced):
        raise ModelRetry(
            "Meta omits reach, frequency, and cpp with breakdowns beyond 13 months. "
            "Remove them from sort and filters, or start the report within 13 months."
        )


def _validate_filters(request: MetaAdsInsightsInput) -> None:
    for item in request.filters or []:
        if item.field not in OBJECT_FILTERS and item.field not in request.fields:
            raise ModelRetry(
                "Use a requested metric or a campaign, adset, or ad name, id, or effective_status in filters.field."
            )
        kind = FILTER_VALUE_KINDS[item.operator]
        if (kind == "list") != isinstance(item.value, list):
            raise ModelRetry(
                "Use a list in filters.value for IN or NOT_IN, and a scalar for other operators."
            )
        if kind == "number" and type(item.value) not in (int, float):
            raise ModelRetry("Use a number in filters.value for GREATER_THAN or LESS_THAN.")
        if kind == "text" and not isinstance(item.value, str):
            raise ModelRetry("Use text in filters.value for CONTAIN or NOT_CONTAIN.")
