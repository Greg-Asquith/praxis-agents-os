# apps/api/integrations/google_analytics/operations/list_report_fields.py

"""List bounded report dimensions and metrics for one Analytics property."""

from typing import Any, Literal

from core.exceptions.integration import IntegrationValidationError
from services.integrations.http import IntegrationRequestPolicy

from ..client import GoogleAnalyticsClient

type ReportFieldKind = Literal["dimensions", "metrics", "both"]


async def list_report_fields(
    client: GoogleAnalyticsClient,
    *,
    property_id: str,
    search: str | None,
    kind: ReportFieldKind,
    custom_only: bool,
    limit: int,
) -> dict[str, Any]:
    payload = await client.data_get(
        f"properties/{property_id}/metadata",
        operation="list_report_fields",
        policy=IntegrationRequestPolicy.READ,
    )
    if not isinstance(payload, dict):
        raise IntegrationValidationError(
            "Google Analytics returned an invalid report metadata response",
            provider_key="google_analytics",
            operation="list_report_fields",
        )
    needle = (search or "").strip().casefold()
    dimensions = (
        _fields(payload.get("dimensions"), needle=needle, custom_only=custom_only, metric=False)
        if kind in {"dimensions", "both"}
        else []
    )
    metrics = (
        _fields(payload.get("metrics"), needle=needle, custom_only=custom_only, metric=True)
        if kind in {"metrics", "both"}
        else []
    )
    dimension_count = len(dimensions)
    metric_count = len(metrics)
    return {
        "dimensions": dimensions[:limit],
        "metrics": metrics[:limit],
        "dimension_count": dimension_count,
        "metric_count": metric_count,
        "truncated": dimension_count > limit or metric_count > limit,
    }


def _fields(raw: Any, *, needle: str, custom_only: bool, metric: bool) -> list[dict[str, Any]]:
    values = raw if isinstance(raw, list) else []
    fields: list[dict[str, Any]] = []
    for item in values:
        if not isinstance(item, dict):
            continue
        api_name = str(item.get("apiName", "")).strip()
        ui_name = str(item.get("uiName", "")).strip()
        custom = bool(item.get("customDefinition")) or api_name.startswith(
            ("customEvent:", "customUser:", "customItem:")
        )
        if not api_name or (custom_only and not custom):
            continue
        if needle and needle not in api_name.casefold() and needle not in ui_name.casefold():
            continue
        value = {
            "api_name": api_name,
            "ui_name": ui_name,
            "description": str(item.get("description", ""))[:300],
            "category": str(item.get("category", "")),
            "custom": custom,
        }
        if metric:
            value["type"] = str(item.get("type", ""))
            blocked_reasons = item.get("blockedReasons", [])
            value["blocked_reasons"] = (
                [str(reason) for reason in blocked_reasons]
                if isinstance(blocked_reasons, list)
                else []
            )
        fields.append(value)
    return fields
