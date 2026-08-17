# apps/api/integrations/google_analytics/operations/run_report.py

"""Run a bounded Google Analytics report for one property."""

import json
from typing import Any

from core.exceptions.integration import IntegrationValidationError
from services.integrations.http import IntegrationRequestPolicy

from ..client import GoogleAnalyticsClient
from ..tools.schemas import GoogleAnalyticsRunReportInput, GoogleAnalyticsValue
from .utils import compile_filter_expression, compile_order_bys

_INTEGER_METRIC_TYPE = "TYPE_INTEGER"


async def run_report(
    client: GoogleAnalyticsClient,
    *,
    property_id: str,
    request: GoogleAnalyticsRunReportInput,
    max_rows: int,
    max_result_chars: int,
) -> dict[str, Any]:
    requested_rows = min(request.limit, max_rows)
    body: dict[str, Any] = {
        "metrics": [{"name": name} for name in request.metrics],
        "dimensions": [{"name": name} for name in request.dimensions],
        "dateRanges": [
            {
                key: value
                for key, value in {
                    "startDate": item.start_date,
                    "endDate": item.end_date,
                    "name": item.name,
                }.items()
                if value is not None
            }
            for item in request.date_ranges
        ],
        "limit": requested_rows + 1,
        "offset": request.offset,
        "keepEmptyRows": request.keep_empty_rows,
    }
    dimension_filter = compile_filter_expression(request.dimension_filter)
    metric_filter = compile_filter_expression(request.metric_filter)
    order_bys = compile_order_bys(request.order_bys)
    if dimension_filter is not None:
        body["dimensionFilter"] = dimension_filter
    if metric_filter is not None:
        body["metricFilter"] = metric_filter
    if order_bys:
        body["orderBys"] = order_bys
    if request.metric_aggregations:
        body["metricAggregations"] = request.metric_aggregations

    payload = await client.data_post(
        f"properties/{property_id}:runReport",
        operation="run_report",
        policy=IntegrationRequestPolicy.READ,
        json=body,
    )
    if not isinstance(payload, dict):
        raise IntegrationValidationError(
            "Google Analytics returned an invalid report response",
            provider_key="google_analytics",
            operation="run_report",
        )

    dimension_headers = _dimension_headers(payload)
    metric_headers = _metric_headers(payload)
    rows = _rows(payload.get("rows"), dimension_headers, metric_headers)
    row_count = _nonnegative_int(payload.get("rowCount"), default=min(len(rows), requested_rows))
    result: dict[str, Any] = {
        "rows": [],
        "row_count": row_count,
        "truncated": len(rows) > requested_rows,
        "truncation_note": None,
        "totals": _rows(payload.get("totals"), dimension_headers, metric_headers),
        "maximums": _rows(payload.get("maximums"), dimension_headers, metric_headers),
        "minimums": _rows(payload.get("minimums"), dimension_headers, metric_headers),
        "metric_headers": metric_headers,
        "dimension_headers": dimension_headers,
        "metadata": _metadata(payload.get("metadata"), request),
    }
    bounded_rows: list[dict[str, GoogleAnalyticsValue]] = []
    for row in rows[:requested_rows]:
        candidate = {**result, "rows": [*bounded_rows, row]}
        if _serialized_chars(candidate) > max_result_chars:
            result["truncated"] = True
            break
        bounded_rows.append(row)
    result["rows"] = bounded_rows
    if result["truncated"]:
        result["truncation_note"] = (
            f"Showing {len(bounded_rows):,} of {row_count:,} rows; add filters, aggregate, "
            "or narrow the date range."
        )
    while bounded_rows and _serialized_chars(result) > max_result_chars:
        bounded_rows.pop()
        result["truncated"] = True
        result["truncation_note"] = (
            f"Showing {len(bounded_rows):,} of {row_count:,} rows; add filters, aggregate, "
            "or narrow the date range."
        )
    if _serialized_chars(result) > max_result_chars:
        raise IntegrationValidationError(
            "Google Analytics report metadata exceeded the safe result-size limit",
            provider_key="google_analytics",
            operation="run_report",
        )
    return result


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


def _metadata(raw: Any, request: GoogleAnalyticsRunReportInput) -> dict[str, Any]:
    metadata = raw if isinstance(raw, dict) else {}
    raw_sampling = metadata.get("samplingMetadatas", [])
    sampling = raw_sampling if isinstance(raw_sampling, list) else []
    notes: list[str] = []
    for index, item in enumerate(sampling[:4]):
        if not isinstance(item, dict):
            continue
        samples_read = _nonnegative_int(item.get("samplesReadCount"), default=0)
        sampling_space = _nonnegative_int(item.get("samplingSpaceSize"), default=0)
        if samples_read >= sampling_space:
            continue
        range_name = request.date_ranges[index].name if index < len(request.date_ranges) else None
        label = range_name or f"date_range_{index}"
        notes.append(
            f"{samples_read:,} of {sampling_space:,} events read for sampled range '{label}'"
        )
    empty_reason = str(metadata.get("emptyReason", "")).strip() or None
    return {
        "currency_code": str(metadata.get("currencyCode", "")),
        "time_zone": str(metadata.get("timeZone", "")),
        "sampled": bool(notes),
        "sampling_notes": notes,
        "active_metric_restrictions": _active_metric_restrictions(metadata),
        "data_loss_from_other_row": bool(metadata.get("dataLossFromOtherRow", False)),
        "thresholded": bool(metadata.get("subjectToThresholding", False)),
        "empty_reason": empty_reason,
    }


def _active_metric_restrictions(metadata: dict[str, Any]) -> list[dict[str, Any]]:
    raw_schema = metadata.get("schemaRestrictionResponse")
    schema = raw_schema if isinstance(raw_schema, dict) else {}
    raw_restrictions = schema.get("activeMetricRestrictions", [])
    restrictions = raw_restrictions if isinstance(raw_restrictions, list) else []
    result: list[dict[str, Any]] = []
    for item in restrictions:
        if not isinstance(item, dict):
            continue
        raw_types = item.get("restrictedMetricTypes", [])
        result.append(
            {
                "metric_name": str(item.get("metricName", "")),
                "restricted_metric_types": (
                    [str(value) for value in raw_types] if isinstance(raw_types, list) else []
                ),
            }
        )
    return result


def _serialized_chars(value: object) -> int:
    return len(
        json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            default=str,
        )
    )


def _nonnegative_int(value: Any, *, default: int) -> int:
    try:
        return max(int(value), 0)
    except (TypeError, ValueError):
        return default
