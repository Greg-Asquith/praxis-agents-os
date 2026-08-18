# apps/api/integrations/google_analytics/operations/check_report_fields.py

"""Check Google Analytics report-field compatibility for one property."""

from typing import Any

from core.exceptions.integration import IntegrationValidationError
from services.integrations.http import IntegrationRequestPolicy

from ..client import GoogleAnalyticsClient
from ..tools.schemas import GoogleAnalyticsCheckReportFieldsInput
from .utils import compile_filter_expression


async def check_report_fields(
    client: GoogleAnalyticsClient,
    *,
    property_id: str,
    request: GoogleAnalyticsCheckReportFieldsInput,
) -> dict[str, Any]:
    body: dict[str, Any] = {
        "metrics": [{"name": name} for name in request.metrics],
        "dimensions": [{"name": name} for name in request.dimensions],
    }
    dimension_filter = compile_filter_expression(request.dimension_filter)
    metric_filter = compile_filter_expression(request.metric_filter)
    if dimension_filter is not None:
        body["dimensionFilter"] = dimension_filter
    if metric_filter is not None:
        body["metricFilter"] = metric_filter
    body["compatibilityFilter"] = "COMPATIBLE"

    payload = await client.data_post(
        f"properties/{property_id}:checkCompatibility",
        operation="check_report_fields",
        policy=IntegrationRequestPolicy.READ,
        json=body,
    )
    if not isinstance(payload, dict):
        raise IntegrationValidationError(
            "Google Analytics returned an invalid field-compatibility response",
            provider_key="google_analytics",
            operation="check_report_fields",
        )

    dimension_compatibility = _compatibilities(
        payload.get("dimensionCompatibilities"),
        "dimensionMetadata",
    )
    metric_compatibility = _compatibilities(
        payload.get("metricCompatibilities"),
        "metricMetadata",
    )
    dimensions = _requested_compatibilities(
        request.candidate_dimensions,
        dimension_compatibility,
    )
    metrics = _requested_compatibilities(request.candidate_metrics, metric_compatibility)
    incompatible_fields = [
        name
        for name in request.candidate_dimensions
        if dimension_compatibility.get(name) != "COMPATIBLE"
    ]
    incompatible_fields.extend(
        name for name in request.candidate_metrics if metric_compatibility.get(name) != "COMPATIBLE"
    )
    return {
        "compatible": not incompatible_fields,
        "dimensions": dimensions,
        "metrics": metrics,
        "incompatible_fields": incompatible_fields,
    }


def _compatibilities(raw: Any, metadata_key: str) -> dict[str, str]:
    if not isinstance(raw, list):
        return {}
    values: dict[str, str] = {}
    for item in raw:
        if not isinstance(item, dict):
            continue
        metadata = item.get(metadata_key)
        if not isinstance(metadata, dict):
            continue
        api_name = str(metadata.get("apiName", "")).strip()
        if not api_name:
            continue
        compatibility = (
            "COMPATIBLE" if item.get("compatibility") == "COMPATIBLE" else "INCOMPATIBLE"
        )
        values[api_name] = compatibility
    return values


def _requested_compatibilities(
    requested: list[str],
    returned: dict[str, str],
) -> list[dict[str, str]]:
    return [
        {
            "api_name": name,
            "compatibility": returned.get(name, "INCOMPATIBLE"),
        }
        for name in requested
    ]
