# apps/api/integrations/google_analytics/operations/utils.py

"""Google Analytics report request compilation and response shaping."""

from typing import Any

from ..tools.schemas import (
    GoogleAnalyticsFieldFilter,
    GoogleAnalyticsOrderBy,
    GoogleAnalyticsValue,
)

_INTEGER_METRIC_TYPE = "TYPE_INTEGER"


def compile_filter_expression(
    filters: list[GoogleAnalyticsFieldFilter] | None,
) -> dict[str, Any] | None:
    if not filters:
        return None
    expressions = [_compile_filter(item) for item in filters]
    if len(expressions) == 1:
        return expressions[0]
    return {"andGroup": {"expressions": expressions}}


def compile_order_bys(order_bys: list[GoogleAnalyticsOrderBy] | None) -> list[dict[str, Any]]:
    compiled: list[dict[str, Any]] = []
    for item in order_bys or []:
        value: dict[str, Any] = {"desc": item.desc}
        if item.metric is not None:
            value["metric"] = {"metricName": item.metric}
        else:
            dimension = {"dimensionName": item.dimension}
            if item.order_type is not None:
                dimension["orderType"] = item.order_type
            value["dimension"] = dimension
        compiled.append(value)
    return compiled


def shape_report_rows(
    payload: dict[str, Any],
    *,
    requested_limit: int,
    window_label: str = "date range",
) -> dict[str, Any]:
    """Shape the row-bearing fields shared by standard and realtime reports."""
    dimension_headers = _dimension_headers(payload)
    metric_headers = _metric_headers(payload)
    rows = _rows(payload.get("rows"), dimension_headers, metric_headers)
    row_count = nonnegative_int(
        payload.get("rowCount"),
        default=min(len(rows), requested_limit),
    )
    truncated = len(rows) > requested_limit
    return {
        "rows": rows[:requested_limit],
        "row_count": row_count,
        "truncated": truncated,
        "truncation_note": (
            f"Showing {min(len(rows), requested_limit):,} of {row_count:,} rows; add filters, "
            f"aggregate, or narrow the {window_label}."
            if truncated
            else None
        ),
        "totals": _rows(payload.get("totals"), dimension_headers, metric_headers),
        "maximums": _rows(payload.get("maximums"), dimension_headers, metric_headers),
        "minimums": _rows(payload.get("minimums"), dimension_headers, metric_headers),
        "metric_headers": metric_headers,
        "dimension_headers": dimension_headers,
    }


def nonnegative_int(value: Any, *, default: int) -> int:
    try:
        return max(int(value), 0)
    except (TypeError, ValueError):
        return default


def _compile_filter(item: GoogleAnalyticsFieldFilter) -> dict[str, Any]:
    filter_value: dict[str, Any] = {"fieldName": item.field_name}
    if item.string_filter is not None:
        filter_value["stringFilter"] = {
            "matchType": item.string_filter.match_type,
            "value": item.string_filter.value,
            "caseSensitive": item.string_filter.case_sensitive,
        }
    elif item.in_list_filter is not None:
        filter_value["inListFilter"] = {
            "values": item.in_list_filter.values,
            "caseSensitive": item.in_list_filter.case_sensitive,
        }
    elif item.numeric_filter is not None:
        filter_value["numericFilter"] = {
            "operation": item.numeric_filter.operation,
            "value": _numeric_value(item.numeric_filter.value),
        }
    else:
        between_filter = item.between_filter
        if between_filter is None:
            raise ValueError("Google Analytics field filter has no leaf filter")
        filter_value["betweenFilter"] = {
            "fromValue": _numeric_value(between_filter.from_value),
            "toValue": _numeric_value(between_filter.to_value),
        }
    expression = {"filter": filter_value}
    return {"notExpression": expression} if item.negate else expression


def _dimension_headers(payload: dict[str, Any]) -> list[str]:
    values = payload.get("dimensionHeaders", [])
    if not isinstance(values, list):
        return []
    return [str(item.get("name", "")) for item in values if isinstance(item, dict)]


def _metric_headers(payload: dict[str, Any]) -> list[dict[str, str]]:
    values = payload.get("metricHeaders", [])
    if not isinstance(values, list):
        return []
    return [
        {"name": str(item.get("name", "")), "type": str(item.get("type", ""))}
        for item in values
        if isinstance(item, dict)
    ]


def _rows(
    raw_rows: Any,
    dimension_headers: list[str],
    metric_headers: list[dict[str, str]],
) -> list[dict[str, GoogleAnalyticsValue]]:
    if not isinstance(raw_rows, list):
        return []
    rows: list[dict[str, GoogleAnalyticsValue]] = []
    for raw_row in raw_rows:
        if not isinstance(raw_row, dict):
            continue
        row: dict[str, GoogleAnalyticsValue] = {}
        dimension_values = raw_row.get("dimensionValues", [])
        if not isinstance(dimension_values, list):
            dimension_values = []
        for index, name in enumerate(dimension_headers):
            row[name] = _raw_value(dimension_values, index)
        metric_values = raw_row.get("metricValues", [])
        if not isinstance(metric_values, list):
            metric_values = []
        for index, header in enumerate(metric_headers):
            row[header["name"]] = _metric_value(
                _raw_value(metric_values, index),
                header["type"],
            )
        rows.append(row)
    return rows


def _raw_value(values: list[Any], index: int) -> str:
    if index >= len(values) or not isinstance(values[index], dict):
        return ""
    return str(values[index].get("value", ""))


def _metric_value(value: str, metric_type: str) -> int | float | None:
    try:
        if metric_type == _INTEGER_METRIC_TYPE:
            return int(value)
        return float(value)
    except (TypeError, ValueError):
        return None


def _numeric_value(value: float) -> dict[str, float | str]:
    if value.is_integer():
        return {"int64Value": str(int(value))}
    return {"doubleValue": value}
