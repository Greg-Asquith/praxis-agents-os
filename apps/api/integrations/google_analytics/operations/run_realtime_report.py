# apps/api/integrations/google_analytics/operations/run_realtime_report.py

"""Run a bounded Google Analytics realtime report for one property."""

from typing import Any

from core.exceptions.integration import IntegrationValidationError
from services.integrations.http import IntegrationRequestPolicy

from ..client import GoogleAnalyticsClient
from ..tools.schemas import GoogleAnalyticsRunRealtimeReportInput
from .utils import compile_filter_expression, compile_order_bys, shape_report_rows


async def run_realtime_report(
    client: GoogleAnalyticsClient,
    *,
    property_id: str,
    request: GoogleAnalyticsRunRealtimeReportInput,
    max_rows: int,
) -> dict[str, Any]:
    requested_rows = min(request.limit, max_rows)
    ranges = request.minute_ranges or []
    body: dict[str, Any] = {
        "metrics": [{"name": name} for name in request.metrics],
        "dimensions": [{"name": name} for name in request.dimensions],
        "minuteRanges": [
            {
                key: value
                for key, value in {
                    "startMinutesAgo": item.start_minutes_ago,
                    "endMinutesAgo": item.end_minutes_ago,
                    "name": item.name,
                }.items()
                if value is not None
            }
            for item in ranges
        ],
        "limit": requested_rows + 1,
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
        f"properties/{property_id}:runRealtimeReport",
        operation="run_realtime_report",
        policy=IntegrationRequestPolicy.READ,
        json=body,
    )
    if not isinstance(payload, dict):
        raise IntegrationValidationError(
            "Google Analytics returned an invalid realtime report response",
            provider_key="google_analytics",
            operation="run_realtime_report",
        )

    result = shape_report_rows(
        payload,
        requested_limit=requested_rows,
        window_label="minute range",
    )
    result["window"] = [
        {
            "start_minutes_ago": item.start_minutes_ago,
            "end_minutes_ago": item.end_minutes_ago,
        }
        for item in ranges
    ]
    return result
