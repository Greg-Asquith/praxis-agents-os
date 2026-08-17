# apps/api/integrations/google_analytics/tools/utils/validation.py

"""Shared local validation for Google Analytics report tools."""

import re

from pydantic_ai import ModelRetry

from ..schemas import GoogleAnalyticsFieldFilter, GoogleAnalyticsOrderBy

_FIELD_NAME_PATTERN = re.compile(r"^[A-Za-z0-9_:]+$")


def validate_field_selection(
    metrics: list[str],
    dimensions: list[str],
    *,
    require_metric: bool = True,
) -> None:
    if require_metric and not 1 <= len(metrics) <= 10:
        raise ModelRetry("Provide between 1 and 10 Google Analytics metrics.")
    if not require_metric and len(metrics) > 10:
        raise ModelRetry("Provide no more than 10 Google Analytics metrics.")
    if len(dimensions) > 9:
        raise ModelRetry("Provide no more than 9 Google Analytics dimensions.")
    for name in (*metrics, *dimensions):
        if not _FIELD_NAME_PATTERN.fullmatch(name):
            raise ModelRetry(
                f"Use an exact Google Analytics API field name for {name!r}; only letters, "
                "numbers, underscores, and colons are allowed."
            )


def validate_filter_kinds(
    filters: list[GoogleAnalyticsFieldFilter] | None,
    *,
    metric: bool,
) -> None:
    for item in filters or []:
        if metric and (item.string_filter is not None or item.in_list_filter is not None):
            raise ModelRetry(
                f"Use numeric_filter or between_filter for metric filter {item.field_name!r}."
            )
        if not metric and (item.numeric_filter is not None or item.between_filter is not None):
            raise ModelRetry(
                f"Use string_filter or in_list_filter for dimension filter {item.field_name!r}."
            )


def validate_order_bys(
    order_bys: list[GoogleAnalyticsOrderBy] | None,
    *,
    metrics: list[str],
    dimensions: list[str],
) -> None:
    for item in order_bys or []:
        if item.metric is not None and item.metric not in metrics:
            raise ModelRetry(f"Add metric {item.metric!r} to metrics before ordering by it.")
        if item.dimension is not None and item.dimension not in dimensions:
            raise ModelRetry(
                f"Add dimension {item.dimension!r} to dimensions before ordering by it."
            )
