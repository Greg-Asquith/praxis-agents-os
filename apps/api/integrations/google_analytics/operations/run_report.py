# apps/api/integrations/google_analytics/operations/run_report.py

"""Run a complete Google Analytics report for one property."""

from typing import Any

from core.exceptions.integration import IntegrationValidationError
from services.integrations.http import IntegrationRequestPolicy
from services.integrations.report_results import ReportResultBudget, report_result_max_bytes

from ..client import GoogleAnalyticsClient
from ..tools.schemas import GoogleAnalyticsRunReportInput
from .utils import (
    compile_filter_expression,
    compile_order_bys,
    nonnegative_int,
    shape_report_rows,
)


async def run_report(
    client: GoogleAnalyticsClient,
    *,
    property_id: str,
    request: GoogleAnalyticsRunReportInput,
    max_response_bytes: int | None = None,
) -> dict[str, Any]:
    budget = ReportResultBudget(
        "google_analytics",
        "run_report",
        maximum=max_response_bytes if max_response_bytes is not None else report_result_max_bytes(),
    )
    page_size = 10_000
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
        "limit": min(request.limit, page_size) if request.limit is not None else page_size,
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

    combined: dict[str, Any] | None = None
    rows: list[Any] = []
    previous_rows = None
    while True:
        payload = await client.data_post(
            f"properties/{property_id}:runReport",
            operation="run_report",
            policy=IntegrationRequestPolicy.READ,
            json=dict(body),
            max_response_bytes=budget.remaining,
        )
        budget.add(payload)
        if not isinstance(payload, dict) or not isinstance(payload.get("rows", []), list):
            raise IntegrationValidationError(
                "Google Analytics returned an invalid report response",
                provider_key="google_analytics",
                operation="run_report",
            )
        page_rows = payload.get("rows", [])
        if combined is None:
            combined = dict(payload)
        elif any(
            payload.get(key) != combined.get(key)
            for key in ("dimensionHeaders", "metricHeaders", "rowCount", "metadata")
        ):
            raise IntegrationValidationError(
                "Google Analytics report changed during pagination. Retry the report.",
                provider_key="google_analytics",
                operation="run_report",
            )
        total = nonnegative_int(payload.get("rowCount"), default=len(page_rows))
        target = max(0, total - request.offset)
        if request.limit is not None:
            target = min(target, request.limit)
        if (not page_rows and len(rows) < target) or (page_rows and page_rows == previous_rows):
            raise IntegrationValidationError(
                "Google Analytics pagination did not advance. No partial report was returned.",
                provider_key="google_analytics",
                operation="run_report",
            )
        rows.extend(page_rows)
        if len(rows) >= target:
            break
        previous_rows = page_rows
        body["offset"] = request.offset + len(rows)
        body["limit"] = min(page_size, target - len(rows))
    combined["rows"] = rows
    result = shape_report_rows(combined, offset=request.offset)
    result["metadata"] = _metadata(combined.get("metadata"), request)
    return result


def _metadata(raw: Any, request: GoogleAnalyticsRunReportInput) -> dict[str, Any]:
    metadata = raw if isinstance(raw, dict) else {}
    raw_sampling = metadata.get("samplingMetadatas", [])
    sampling = raw_sampling if isinstance(raw_sampling, list) else []
    notes: list[str] = []
    for index, item in enumerate(sampling[:4]):
        if not isinstance(item, dict):
            continue
        samples_read = nonnegative_int(item.get("samplesReadCount"), default=0)
        sampling_space = nonnegative_int(item.get("samplingSpaceSize"), default=0)
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
