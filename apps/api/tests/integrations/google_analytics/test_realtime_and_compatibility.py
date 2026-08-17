"""Google Analytics realtime and compatibility tool contracts."""

from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from pydantic_ai import ModelRetry

from core.exceptions.integration import IntegrationAuthError, IntegrationValidationError
from integrations.google_analytics.operations.check_report_fields import check_report_fields
from integrations.google_analytics.operations.run_realtime_report import run_realtime_report
from integrations.google_analytics.tools import TOOL_DEFINITIONS
from integrations.google_analytics.tools.check_report_fields import (
    google_analytics_check_report_fields,
)
from integrations.google_analytics.tools.run_realtime_report import (
    DEFINITION as RUN_REALTIME_REPORT_DEFINITION,
    google_analytics_run_realtime_report,
)
from integrations.google_analytics.tools.schemas import (
    GoogleAnalyticsCheckReportFieldsInput,
    GoogleAnalyticsFieldFilter,
    GoogleAnalyticsMinuteRange,
    GoogleAnalyticsNumericFilter,
    GoogleAnalyticsOrderBy,
    GoogleAnalyticsRunRealtimeReportInput,
    GoogleAnalyticsStringFilter,
)
from services.integrations.context.domain import ResolvedActiveContext, ResolvedContextEntry
from services.integrations.http import IntegrationRequestPolicy


class _Client:
    def __init__(self, payload: Any) -> None:
        self.payload = payload
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def data_post(self, path: str, **kwargs: Any) -> Any:
        self.calls.append((path, kwargs))
        return self.payload


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


def _ctx(*entries: ResolvedContextEntry, tool_name: str):
    return SimpleNamespace(
        deps=SimpleNamespace(
            active_context=ResolvedActiveContext(entries=entries),
            workspace=SimpleNamespace(id=uuid4()),
            agent=SimpleNamespace(id=uuid4(), name="Analytics Agent"),
            run=SimpleNamespace(id=uuid4(), user_id=uuid4()),
        ),
        tool_name=tool_name,
        tool_call_id="call-ga4-realtime",
    )


async def test_realtime_operation_compiles_two_ranges_and_shapes_range_key() -> None:
    client = _Client(
        {
            "dimensionHeaders": [{"name": "dateRange"}, {"name": "country"}],
            "metricHeaders": [{"name": "activeUsers", "type": "TYPE_INTEGER"}],
            "rows": [
                {
                    "dimensionValues": [{"value": "recent"}, {"value": "GB"}],
                    "metricValues": [{"value": "12"}],
                },
                {
                    "dimensionValues": [{"value": "earlier"}, {"value": "US"}],
                    "metricValues": [{"value": "5"}],
                },
                {
                    "dimensionValues": [{"value": "recent"}, {"value": "FR"}],
                    "metricValues": [{"value": "1"}],
                },
            ],
            "rowCount": 3,
        }
    )
    request = GoogleAnalyticsRunRealtimeReportInput(
        metrics=["activeUsers"],
        dimensions=["country"],
        minute_ranges=[
            GoogleAnalyticsMinuteRange(
                start_minutes_ago=4,
                end_minutes_ago=0,
                name="recent",
            ),
            GoogleAnalyticsMinuteRange(
                start_minutes_ago=9,
                end_minutes_ago=5,
                name="earlier",
            ),
        ],
        dimension_filter=[
            GoogleAnalyticsFieldFilter(
                field_name="country",
                string_filter=GoogleAnalyticsStringFilter(match_type="EXACT", value="GB"),
            )
        ],
        order_bys=[GoogleAnalyticsOrderBy(metric="activeUsers", desc=True)],
        limit=2,
        metric_aggregations=["TOTAL"],
    )

    result = await run_realtime_report(
        client,
        property_id="123",
        request=request,
        max_rows=1000,
    )

    path, call = client.calls[0]
    assert path == "properties/123:runRealtimeReport"
    assert call["operation"] == "run_realtime_report"
    assert call["policy"] is IntegrationRequestPolicy.READ
    assert call["json"]["limit"] == 3
    assert call["json"]["minuteRanges"][1] == {
        "startMinutesAgo": 9,
        "endMinutesAgo": 5,
        "name": "earlier",
    }
    assert call["json"]["dimensionFilter"]["filter"]["fieldName"] == "country"
    assert call["json"]["orderBys"] == [{"metric": {"metricName": "activeUsers"}, "desc": True}]
    assert call["json"]["metricAggregations"] == ["TOTAL"]
    assert result["rows"] == [
        {"dateRange": "recent", "country": "GB", "activeUsers": 12},
        {"dateRange": "earlier", "country": "US", "activeUsers": 5},
    ]
    assert result["row_count"] == 3
    assert result["truncated"] is True
    assert result["window"][0]["start_minutes_ago"] == 4


async def test_compatibility_operation_maps_candidates_from_compatible_catalog() -> None:
    client = _Client(
        {
            "dimensionCompatibilities": [
                {
                    "dimensionMetadata": {"apiName": "country"},
                    "compatibility": "COMPATIBLE",
                }
            ],
            "metricCompatibilities": [
                {
                    "metricMetadata": {"apiName": "activeUsers"},
                    "compatibility": "COMPATIBLE",
                }
            ],
        }
    )
    request = GoogleAnalyticsCheckReportFieldsInput(
        metrics=["sessions"],
        dimensions=["country"],
        candidate_metrics=["activeUsers", "eventCount"],
        candidate_dimensions=["itemName"],
        metric_filter=[
            GoogleAnalyticsFieldFilter(
                field_name="sessions",
                numeric_filter=GoogleAnalyticsNumericFilter(operation="GREATER_THAN", value=0),
            )
        ],
    )

    result = await check_report_fields(client, property_id="123", request=request)

    path, call = client.calls[0]
    assert path == "properties/123:checkCompatibility"
    assert call["operation"] == "check_report_fields"
    assert call["policy"] is IntegrationRequestPolicy.READ
    assert call["json"]["compatibilityFilter"] == "COMPATIBLE"
    assert call["json"]["metrics"] == [{"name": "sessions"}]
    assert call["json"]["dimensions"] == [{"name": "country"}]
    assert call["json"]["metricFilter"]["filter"]["fieldName"] == "sessions"
    assert result == {
        "compatible": False,
        "dimensions": [{"api_name": "itemName", "compatibility": "INCOMPATIBLE"}],
        "metrics": [
            {"api_name": "activeUsers", "compatibility": "COMPATIBLE"},
            {"api_name": "eventCount", "compatibility": "INCOMPATIBLE"},
        ],
        "incompatible_fields": ["itemName", "eventCount"],
    }


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"metrics": []}, "between 1 and 10"),
        ({"dimensions": [f"dimension_{index}" for index in range(10)]}, "no more than 9"),
        ({"minute_ranges": []}, "one or two"),
        ({"metrics": ["active-users"]}, "exact Google Analytics API field name"),
        (
            {
                "minute_ranges": [
                    GoogleAnalyticsMinuteRange.model_construct(
                        start_minutes_ago=30,
                        end_minutes_ago=0,
                        name=None,
                    )
                ]
            },
            "between 0 and 29",
        ),
        (
            {
                "minute_ranges": [
                    GoogleAnalyticsMinuteRange.model_construct(
                        start_minutes_ago=2,
                        end_minutes_ago=3,
                        name=None,
                    )
                ]
            },
            "greater than or equal",
        ),
        (
            {
                "minute_ranges": [
                    GoogleAnalyticsMinuteRange.model_construct(
                        start_minutes_ago=29,
                        end_minutes_ago=0,
                        name="RESERVED_recent",
                    )
                ]
            },
            "does not begin with date_range_ or RESERVED_",
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
    ],
)
async def test_realtime_local_validation_returns_actionable_model_retry(
    kwargs: dict[str, Any],
    message: str,
) -> None:
    values = {"metrics": ["activeUsers"], "dimensions": ["country"]}
    values.update(kwargs)

    with pytest.raises(ModelRetry, match=message):
        await google_analytics_run_realtime_report(
            _ctx(_entry("111"), tool_name="google_analytics_run_realtime_report"),
            **values,
        )


def test_realtime_tool_schema_explains_minute_range_order() -> None:
    schema = RUN_REALTIME_REPORT_DEFINITION.serialized_input_schema()

    assert schema is not None
    minute_ranges = schema["properties"]["minute_ranges"]
    description = minute_ranges["description"]
    assert "start_minutes_ago is the older boundary" in description
    assert "greater than or equal to" in description
    assert minute_ranges["examples"] == [[{"start_minutes_ago": 29, "end_minutes_ago": 0}]]

    range_schema = schema["$defs"]["GoogleAnalyticsMinuteRange"]
    start = range_schema["properties"]["start_minutes_ago"]
    end = range_schema["properties"]["end_minutes_ago"]
    assert "Older boundary" in start["description"]
    assert start["examples"] == [29]
    assert "Newer boundary" in end["description"]
    assert end["examples"] == [0]


async def test_realtime_defaults_to_last_thirty_minutes_and_audits_without_rows(
    monkeypatch,
) -> None:
    entry = _entry("111")
    audit = AsyncMock(return_value=uuid4())
    provider = AsyncMock(
        return_value={
            "rows": [{"country": "GB", "activeUsers": 12}],
            "row_count": 1,
            "truncated": False,
            "truncation_note": None,
            "totals": [],
            "maximums": [],
            "minimums": [],
            "metric_headers": [{"name": "activeUsers", "type": "TYPE_INTEGER"}],
            "dimension_headers": ["country"],
            "window": [{"start_minutes_ago": 29, "end_minutes_ago": 0}],
        }
    )
    monkeypatch.setattr(
        "services.integrations.operations.record_integration_operation_audit_event",
        audit,
    )
    monkeypatch.setattr(
        "integrations.google_analytics.tools.run_realtime_report.google_analytics_client",
        lambda _ctx, _entry: _async_value("client"),
    )
    monkeypatch.setattr(
        "integrations.google_analytics.tools.run_realtime_report.run_realtime_report",
        provider,
    )

    result = await google_analytics_run_realtime_report(
        _ctx(entry, tool_name="google_analytics_run_realtime_report"),
        metrics=["activeUsers"],
        dimensions=["country"],
    )

    request = provider.await_args.kwargs["request"]
    assert [(item.start_minutes_ago, item.end_minutes_ago) for item in request.minute_ranges] == [
        (29, 0)
    ]
    assert result["results"][0]["status"] == "success"
    detail = audit.await_args.kwargs["operation_detail"].model_dump(mode="json")
    assert detail["intent_groups"][0]["items"][0]["fields"] == {
        "metric_count": 1,
        "dimension_count": 1,
        "window": [{"start_minutes_ago": 29, "end_minutes_ago": 0}],
    }
    assert "rows" not in str(detail)


async def test_compatibility_local_validation_rejects_metric_string_filter() -> None:
    with pytest.raises(ModelRetry, match="numeric_filter or between_filter"):
        await google_analytics_check_report_fields(
            _ctx(_entry("111"), tool_name="google_analytics_check_report_fields"),
            metrics=["activeUsers"],
            dimensions=[],
            candidate_metrics=["eventCount"],
            candidate_dimensions=[],
            metric_filter=[
                GoogleAnalyticsFieldFilter(
                    field_name="activeUsers",
                    string_filter=GoogleAnalyticsStringFilter(
                        match_type="EXACT",
                        value="1",
                    ),
                )
            ],
        )


def test_new_tool_definitions_use_the_frozen_read_contract() -> None:
    definitions = {
        item.name: item
        for item in TOOL_DEFINITIONS
        if item.name
        in {
            "google_analytics_check_report_fields",
            "google_analytics_run_realtime_report",
        }
    }

    for definition in definitions.values():
        assert definition.effect == "read"
        assert definition.egress == "provider_query"
        assert definition.default_policy == "auto"
        assert definition.code_eligible is True
        assert definition.timeout == 30
        assert definition.presentation.icon == "google_analytics"
        assert [field.key for field in definition.presentation.result_fields] == ["results"]
    assert [
        field.key
        for field in definitions["google_analytics_run_realtime_report"].presentation.arg_fields
    ] == ["metrics", "dimensions", "limit"]
    assert [
        field.key
        for field in definitions["google_analytics_check_report_fields"].presentation.arg_fields
    ] == ["metrics", "dimensions", "candidate_metrics", "candidate_dimensions"]


@pytest.mark.parametrize(
    ("candidate_metrics", "candidate_dimensions", "message"),
    [
        ([], [], "at least one candidate"),
        (["sessions"], [], "already appear in the base report"),
    ],
)
async def test_compatibility_requires_distinct_candidate_fields(
    candidate_metrics: list[str],
    candidate_dimensions: list[str],
    message: str,
) -> None:
    with pytest.raises(ModelRetry, match=message):
        await google_analytics_check_report_fields(
            _ctx(_entry("111"), tool_name="google_analytics_check_report_fields"),
            metrics=["sessions"],
            dimensions=[],
            candidate_metrics=candidate_metrics,
            candidate_dimensions=candidate_dimensions,
        )


async def test_compatibility_fan_out_isolates_failure_and_audits_counts(monkeypatch) -> None:
    entries = (_entry("111"), _entry("222"))
    audit = AsyncMock(return_value=uuid4())
    monkeypatch.setattr(
        "services.integrations.operations.record_integration_operation_audit_event",
        audit,
    )
    monkeypatch.setattr(
        "integrations.google_analytics.tools.check_report_fields.google_analytics_client",
        lambda _ctx, entry: _async_value(entry.external_id),
    )

    async def provider_check(client, **_kwargs):
        if client == "222":
            raise IntegrationAuthError("permission denied", provider_key="google_analytics")
        return {
            "compatible": False,
            "dimensions": [{"api_name": "itemName", "compatibility": "INCOMPATIBLE"}],
            "metrics": [{"api_name": "activeUsers", "compatibility": "COMPATIBLE"}],
            "incompatible_fields": ["itemName"],
        }

    monkeypatch.setattr(
        "integrations.google_analytics.tools.check_report_fields.check_report_fields",
        provider_check,
    )

    result = await google_analytics_check_report_fields(
        _ctx(*entries, tool_name="google_analytics_check_report_fields"),
        metrics=["activeUsers"],
        dimensions=[],
        candidate_metrics=[],
        candidate_dimensions=["itemName"],
    )

    assert [item["status"] for item in result["results"]] == ["success", "error"]
    assert result["results"][1]["error_code"] == "IntegrationAuthError"
    detail = audit.await_args_list[0].kwargs["operation_detail"].model_dump(mode="json")
    assert detail["intent_groups"][0]["items"][0]["fields"] == {
        "metric_count": 1,
        "dimension_count": 0,
        "candidate_metric_count": 0,
        "candidate_dimension_count": 1,
        "compatible": False,
    }
    assert all(str(entry.integration_resource_id) not in str(result) for entry in entries)


@pytest.mark.parametrize("operation", ["realtime", "compatibility"])
async def test_new_operations_fail_closed_on_non_object_response(operation: str) -> None:
    client = _Client([])
    with pytest.raises(IntegrationValidationError, match="invalid"):
        if operation == "realtime":
            await run_realtime_report(
                client,
                property_id="123",
                request=GoogleAnalyticsRunRealtimeReportInput(
                    metrics=["activeUsers"],
                    dimensions=[],
                    minute_ranges=[
                        GoogleAnalyticsMinuteRange(start_minutes_ago=29, end_minutes_ago=0)
                    ],
                ),
                max_rows=1000,
            )
        else:
            await check_report_fields(
                client,
                property_id="123",
                request=GoogleAnalyticsCheckReportFieldsInput(
                    metrics=["activeUsers"],
                    dimensions=[],
                    candidate_metrics=[],
                    candidate_dimensions=["itemName"],
                ),
            )


async def _async_value(value):
    return value
