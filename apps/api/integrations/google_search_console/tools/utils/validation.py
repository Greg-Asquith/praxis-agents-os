# apps/api/integrations/google_search_console/tools/utils/validation.py

"""Local validation for Google Search Console tool requests."""

from datetime import date
from typing import Any

from pydantic import ValidationError
from pydantic_ai import ModelRetry

from core.settings import settings

from ...operations.query_search_analytics import MAX_SEARCH_ANALYTICS_ROWS
from ..schemas import GoogleSearchConsoleSearchAnalyticsInput


def validated_search_analytics_request(
    **values: Any,
) -> GoogleSearchConsoleSearchAnalyticsInput:
    """Returns a locally validated Search Analytics request."""
    start_date = _absolute_date(values["start_date"], field="start_date")
    end_date = _absolute_date(values["end_date"], field="end_date")
    if start_date > end_date:
        raise ModelRetry("Set start_date on or before end_date.")
    if start_date < _subtract_months(end_date, 16):
        raise ModelRetry("Keep the Search Console date range within 16 months.")

    dimensions = values["dimensions"]
    if len(dimensions) != len(set(dimensions)):
        raise ModelRetry("Remove duplicate Search Console dimensions.")
    max_rows = min(settings.INTEGRATION_REPORT_MAX_ROWS, MAX_SEARCH_ANALYTICS_ROWS)
    if values["row_limit"] > max_rows:
        raise ModelRetry(f"Set row_limit to {max_rows:,} rows or fewer.")
    filters = values.get("filters") or []
    has_page = "page" in dimensions or any(item.dimension == "page" for item in filters)
    if values["aggregation_type"] == "byProperty" and has_page:
        raise ModelRetry("Use auto or byPage aggregation when grouping or filtering by page.")
    if values["aggregation_type"] == "byProperty" and values["search_type"] in {
        "discover",
        "googleNews",
    }:
        raise ModelRetry("Use auto aggregation for Discover and Google News searches.")
    try:
        return GoogleSearchConsoleSearchAnalyticsInput.model_validate(values)
    except ValidationError as exc:
        message = exc.errors(include_url=False)[0]["msg"]
        raise ModelRetry(f"Correct the Search Console query: {message}.") from exc


def _absolute_date(value: str, *, field: str) -> date:
    try:
        parsed = date.fromisoformat(value)
    except (TypeError, ValueError):
        raise ModelRetry(f"Set {field} to an absolute date in YYYY-MM-DD format.") from None
    if parsed.isoformat() != value:
        raise ModelRetry(f"Set {field} to an absolute date in YYYY-MM-DD format.")
    return parsed


def _subtract_months(value: date, months: int) -> date:
    month_index = value.year * 12 + value.month - 1 - months
    if month_index < 12:
        return date.min
    year, zero_based_month = divmod(month_index, 12)
    month = zero_based_month + 1
    next_month = date(year + 1, 1, 1) if month == 12 else date(year, month + 1, 1)
    last_day = (next_month - date.resolution).day
    return date(year, month, min(value.day, last_day))
