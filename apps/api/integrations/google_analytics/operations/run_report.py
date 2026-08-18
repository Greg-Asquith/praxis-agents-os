# apps/api/integrations/google_analytics/operations/run_report.py

"""Run a bounded Google Analytics report for one property."""

from typing import Any

from core.exceptions.integration import IntegrationValidationError
from services.integrations.http import IntegrationRequestPolicy

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
    max_rows: int,
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

    result = shape_report_rows(payload, requested_limit=requested_rows)
    result["metadata"] = _metadata(payload.get("metadata"), request)
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
