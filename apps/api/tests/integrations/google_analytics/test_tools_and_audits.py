"""Google Analytics tool validation, fan-out, and audit behavior."""

from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from pydantic_ai import ModelRetry

from core.exceptions.integration import IntegrationAuthError
from integrations.google_analytics.tools.list_report_fields import (
    google_analytics_list_report_fields,
)
from integrations.google_analytics.tools.run_report import google_analytics_run_report
from integrations.google_analytics.tools.schemas import (
    GoogleAnalyticsDateRange,
    GoogleAnalyticsFieldFilter,
    GoogleAnalyticsNumericFilter,
    GoogleAnalyticsOrderBy,
)
from services.integrations.context.domain import ResolvedActiveContext, ResolvedContextEntry


def _entry(external_id: str) -> ResolvedContextEntry:
    return ResolvedContextEntry(
        integration_resource_id=uuid4(),
        provider_key="google_analytics",
        resource_type="google_analytics_property",
        external_id=external_id,
        display_name=f"Property {external_id}",
        connection_id=uuid4(),
        connection_label="Analytics",
        connection_status="active",
        write_allowed=False,
    )


def _ctx(*entries: ResolvedContextEntry, tool_name: str = "google_analytics_run_report"):
    return SimpleNamespace(
        deps=SimpleNamespace(
            active_context=ResolvedActiveContext(entries=entries),
            workspace=SimpleNamespace(id=uuid4()),
            agent=SimpleNamespace(id=uuid4(), name="Analytics Agent"),
            run=SimpleNamespace(id=uuid4(), user_id=uuid4()),
        ),
        tool_name=tool_name,
        tool_call_id="call-ga4-report",
    )


def _dates(start: str = "28daysAgo") -> list[GoogleAnalyticsDateRange]:
    return [GoogleAnalyticsDateRange(start_date=start, end_date="yesterday")]


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"metrics": []}, "between 1 and 10"),
        ({"dimensions": [f"dimension_{index}" for index in range(10)]}, "no more than 9"),
        ({"date_ranges": _dates("not-a-date")}, "YYYY-MM-DD"),
        ({"date_ranges": _dates("20260817")}, "YYYY-MM-DD"),
        ({"date_ranges": _dates("2026-W33-1")}, "YYYY-MM-DD"),
        (
            {
                "date_ranges": [
                    GoogleAnalyticsDateRange(
                        start_date="2026-08-18",
                        end_date="2026-08-17",
                    )
                ]
            },
            "on or before",
        ),
        (
            {
                "date_ranges": [
                    GoogleAnalyticsDateRange(
                        start_date="yesterday",
                        end_date="yesterday",
                        name="date_range_custom",
                    )
                ]
            },
            "does not begin",
        ),
        (
            {
                "dimension_filter": [
                    GoogleAnalyticsFieldFilter(
                        field_name="country",
                        numeric_filter=GoogleAnalyticsNumericFilter(
                            operation="EQUAL",
                            value=1,
                        ),
                    )
                ]
            },
            "string_filter or in_list_filter",
        ),
        (
            {"order_bys": [GoogleAnalyticsOrderBy(metric="totalUsers")]},
            "Add metric 'totalUsers'",
        ),
    ],
)
async def test_run_report_local_validation_returns_actionable_model_retry(
    kwargs,
    message: str,
) -> None:
    values = {
        "metrics": ["sessions"],
        "dimensions": ["country"],
        "date_ranges": _dates(),
    }
    values.update(kwargs)

    with pytest.raises(ModelRetry, match=message):
        await google_analytics_run_report(_ctx(_entry("1")), **values)


async def test_run_report_fans_out_partial_success_without_platform_ids(monkeypatch) -> None:
    entries = (_entry("111"), _entry("222"))
    audit = AsyncMock(return_value=uuid4())
    monkeypatch.setattr(
        "services.integrations.operations.record_integration_operation_audit_event",
        audit,
    )
    monkeypatch.setattr(
        "integrations.google_analytics.tools.run_report.google_analytics_client",
        lambda _ctx, entry: _async_value(entry.external_id),
    )

    async def provider_report(client, **_kwargs):
        if client == "222":
            raise IntegrationAuthError("permission denied", provider_key="google_analytics")
        return {
            "rows": [{"country": "UK", "sessions": 12}],
            "row_count": 1,
            "truncated": False,
            "truncation_note": None,
            "totals": [],
            "maximums": [],
            "minimums": [],
            "metric_headers": [{"name": "sessions", "type": "TYPE_INTEGER"}],
            "dimension_headers": ["country"],
            "metadata": {
                "currency_code": "GBP",
                "time_zone": "Europe/London",
                "sampled": False,
                "sampling_notes": [],
                "active_metric_restrictions": [],
                "data_loss_from_other_row": False,
                "thresholded": False,
                "empty_reason": None,
            },
        }

    monkeypatch.setattr(
        "integrations.google_analytics.tools.run_report.run_report",
        provider_report,
    )

    result = await google_analytics_run_report(
        _ctx(*entries),
        metrics=["sessions"],
        dimensions=["country"],
        date_ranges=_dates(),
    )

    assert [item["status"] for item in result["results"]] == ["success", "error"]
    assert result["results"][1]["error_code"] == "IntegrationAuthError"
    serialized = str(result)
    assert str(entries[0].integration_resource_id) not in serialized
    assert str(entries[0].connection_id) not in serialized
    assert audit.await_count == 2
    successful_audit = audit.await_args_list[0].kwargs
    assert successful_audit["operation"] == "run_report"
    assert successful_audit["operation_detail"] is None
    assert "rows" not in successful_audit


async def test_list_report_fields_uses_standard_row_free_operation_audit(monkeypatch) -> None:
    entry = _entry("111")
    audit = AsyncMock(return_value=uuid4())
    monkeypatch.setattr(
        "services.integrations.operations.record_integration_operation_audit_event",
        audit,
    )
    monkeypatch.setattr(
        "integrations.google_analytics.tools.list_report_fields.google_analytics_client",
        lambda _ctx, _entry: _async_value("client"),
    )
    monkeypatch.setattr(
        "integrations.google_analytics.tools.list_report_fields.list_report_fields",
        AsyncMock(
            return_value={
                "dimensions": [],
                "metrics": [],
                "dimension_count": 0,
                "metric_count": 0,
                "truncated": False,
            }
        ),
    )

    result = await google_analytics_list_report_fields(
        _ctx(entry, tool_name="google_analytics_list_report_fields"),
        search=" custom ",
    )

    assert result["results"][0]["status"] == "success"
    kwargs = audit.await_args.kwargs
    assert kwargs["operation"] == "list_report_fields"
    assert kwargs["operation_detail"] is None
    assert "dimensions" not in kwargs


async def test_malformed_provider_response_fans_out_as_error_and_is_audited(monkeypatch) -> None:
    entry = _entry("111")
    audit = AsyncMock(return_value=uuid4())
    monkeypatch.setattr(
        "services.integrations.operations.record_integration_operation_audit_event",
        audit,
    )
    monkeypatch.setattr(
        "integrations.google_analytics.tools.run_report.google_analytics_client",
        lambda _ctx, _entry: _async_value(_MalformedClient()),
    )

    result = await google_analytics_run_report(
        _ctx(entry),
        metrics=["sessions"],
        dimensions=[],
        date_ranges=_dates(),
    )

    assert result["results"][0]["status"] == "error"
    assert result["results"][0]["error_code"] == "IntegrationValidationError"
    assert audit.await_args.kwargs["status"] == "failure"
    assert audit.await_args.kwargs["error_code"] == "IntegrationValidationError"


class _MalformedClient:
    async def data_post(self, *_args, **_kwargs):
        return []


async def _async_value(value):
    return value
