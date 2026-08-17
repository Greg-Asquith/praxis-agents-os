"""Google Analytics report request compilation and response shaping."""

import json
from typing import Any

import pytest

from core.exceptions.integration import IntegrationValidationError
from integrations.google_analytics.operations.list_report_fields import list_report_fields
from integrations.google_analytics.operations.run_report import run_report
from integrations.google_analytics.operations.utils import (
    compile_filter_expression,
    compile_order_bys,
)
from integrations.google_analytics.tools.schemas import (
    GoogleAnalyticsBetweenFilter,
    GoogleAnalyticsDateRange,
    GoogleAnalyticsFieldFilter,
    GoogleAnalyticsInListFilter,
    GoogleAnalyticsNumericFilter,
    GoogleAnalyticsOrderBy,
    GoogleAnalyticsRunReportInput,
    GoogleAnalyticsStringFilter,
)
from services.integrations.http import IntegrationRequestPolicy


class _Client:
    def __init__(self, payload: Any) -> None:
        self.payload = payload
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def data_post(self, path: str, **kwargs: Any) -> Any:
        self.calls.append((path, kwargs))
        return self.payload

    async def data_get(self, path: str, **kwargs: Any) -> Any:
        self.calls.append((path, kwargs))
        return self.payload


def test_filter_and_order_compilers_emit_exact_api_casing() -> None:
    filters = [
        GoogleAnalyticsFieldFilter(
            field_name="country",
            string_filter=GoogleAnalyticsStringFilter(
                match_type="EXACT",
                value="United Kingdom",
            ),
        ),
        GoogleAnalyticsFieldFilter(
            field_name="city",
            negate=True,
            in_list_filter=GoogleAnalyticsInListFilter(values=["London", "Leeds"]),
        ),
    ]
    metric_filters = [
        GoogleAnalyticsFieldFilter(
            field_name="sessions",
            numeric_filter=GoogleAnalyticsNumericFilter(
                operation="GREATER_THAN",
                value=10,
            ),
        ),
        GoogleAnalyticsFieldFilter(
            field_name="engagementRate",
            between_filter=GoogleAnalyticsBetweenFilter(from_value=0.25, to_value=0.75),
        ),
    ]

    assert compile_filter_expression(filters) == {
        "andGroup": {
            "expressions": [
                {
                    "filter": {
                        "fieldName": "country",
                        "stringFilter": {
                            "matchType": "EXACT",
                            "value": "United Kingdom",
                            "caseSensitive": False,
                        },
                    }
                },
                {
                    "notExpression": {
                        "filter": {
                            "fieldName": "city",
                            "inListFilter": {
                                "values": ["London", "Leeds"],
                                "caseSensitive": False,
                            },
                        }
                    }
                },
            ]
        }
    }
    assert compile_filter_expression(metric_filters) == {
        "andGroup": {
            "expressions": [
                {
                    "filter": {
                        "fieldName": "sessions",
                        "numericFilter": {
                            "operation": "GREATER_THAN",
                            "value": {"int64Value": "10"},
                        },
                    }
                },
                {
                    "filter": {
                        "fieldName": "engagementRate",
                        "betweenFilter": {
                            "fromValue": {"doubleValue": 0.25},
                            "toValue": {"doubleValue": 0.75},
                        },
                    }
                },
            ]
        }
    }
    assert compile_order_bys(
        [
            GoogleAnalyticsOrderBy(metric="sessions", desc=True),
            GoogleAnalyticsOrderBy(dimension="country", order_type="ALPHANUMERIC"),
        ]
    ) == [
        {"metric": {"metricName": "sessions"}, "desc": True},
        {
            "dimension": {"dimensionName": "country", "orderType": "ALPHANUMERIC"},
            "desc": False,
        },
    ]


async def test_run_report_compiles_request_and_types_rows_aggregates_and_metadata() -> None:
    client = _Client(
        {
            "dimensionHeaders": [{"name": "dateRange"}, {"name": "country"}],
            "metricHeaders": [
                {"name": "sessions", "type": "TYPE_INTEGER"},
                {"name": "engagementRate", "type": "TYPE_FLOAT"},
                {"name": "badMetric", "type": "TYPE_SECONDS"},
            ],
            "rows": [
                {
                    "dimensionValues": [{"value": "current"}, {"value": "UK"}],
                    "metricValues": [
                        {"value": "12"},
                        {"value": "0.75"},
                        {"value": "not-a-number"},
                    ],
                },
                {
                    "dimensionValues": [{"value": "previous"}, {"value": "US"}],
                    "metricValues": [{"value": "5"}, {"value": "0.5"}, {"value": "2"}],
                },
                {
                    "dimensionValues": [{"value": "current"}, {"value": "FR"}],
                    "metricValues": [{"value": "1"}, {"value": "0.1"}, {"value": "1"}],
                },
            ],
            "totals": [{"metricValues": [{"value": "18"}, {"value": "1.35"}]}],
            "maximums": [{"metricValues": [{"value": "12"}, {"value": "0.75"}]}],
            "minimums": [{"metricValues": [{"value": "1"}, {"value": "0.1"}]}],
            "rowCount": 4213,
            "metadata": {
                "currencyCode": "GBP",
                "timeZone": "Europe/London",
                "dataLossFromOtherRow": True,
                "subjectToThresholding": True,
                "samplingMetadatas": [
                    {"samplesReadCount": "12000", "samplingSpaceSize": "40000"},
                    {"samplesReadCount": "100", "samplingSpaceSize": "100"},
                ],
                "schemaRestrictionResponse": {
                    "activeMetricRestrictions": [
                        {
                            "metricName": "purchaseRevenue",
                            "restrictedMetricTypes": ["REVENUE_DATA"],
                        }
                    ]
                },
            },
        }
    )
    request = GoogleAnalyticsRunReportInput(
        metrics=["sessions", "engagementRate", "badMetric"],
        dimensions=["country"],
        date_ranges=[
            GoogleAnalyticsDateRange(
                start_date="28daysAgo",
                end_date="yesterday",
                name="current",
            ),
            GoogleAnalyticsDateRange(
                start_date="56daysAgo",
                end_date="29daysAgo",
                name="previous",
            ),
        ],
        metric_filter=[
            GoogleAnalyticsFieldFilter(
                field_name="sessions",
                numeric_filter=GoogleAnalyticsNumericFilter(
                    operation="GREATER_THAN",
                    value=10,
                ),
            )
        ],
        order_bys=[GoogleAnalyticsOrderBy(metric="sessions", desc=True)],
        limit=2,
        offset=4,
        metric_aggregations=["TOTAL", "MAXIMUM", "MINIMUM"],
    )

    result = await run_report(
        client,
        property_id="123",
        request=request,
        max_rows=1000,
        max_result_chars=16_000,
    )

    path, call = client.calls[0]
    assert path == "properties/123:runReport"
    assert call["operation"] == "run_report"
    assert call["policy"] is IntegrationRequestPolicy.READ
    assert call["json"]["limit"] == 3
    assert call["json"]["offset"] == 4
    assert call["json"]["dateRanges"][1]["name"] == "previous"
    assert call["json"]["metricAggregations"] == ["TOTAL", "MAXIMUM", "MINIMUM"]
    assert result["rows"] == [
        {
            "dateRange": "current",
            "country": "UK",
            "sessions": 12,
            "engagementRate": 0.75,
            "badMetric": None,
        },
        {
            "dateRange": "previous",
            "country": "US",
            "sessions": 5,
            "engagementRate": 0.5,
            "badMetric": 2.0,
        },
    ]
    assert result["row_count"] == 4213
    assert result["truncated"] is True
    assert result["truncation_note"] == (
        "Showing 2 of 4,213 rows; add filters, aggregate, or narrow the date range."
    )
    assert result["totals"][0]["sessions"] == 18
    assert result["maximums"][0]["engagementRate"] == 0.75
    assert result["minimums"][0]["sessions"] == 1
    assert result["metadata"] == {
        "currency_code": "GBP",
        "time_zone": "Europe/London",
        "sampled": True,
        "sampling_notes": [
            "12,000 of 40,000 events read for sampled range 'current'",
        ],
        "active_metric_restrictions": [
            {
                "metric_name": "purchaseRevenue",
                "restricted_metric_types": ["REVENUE_DATA"],
            }
        ],
        "data_loss_from_other_row": True,
        "thresholded": True,
        "empty_reason": None,
    }


async def test_run_report_shapes_empty_response() -> None:
    client = _Client({"metadata": {"emptyReason": "NO_DATA"}})
    request = GoogleAnalyticsRunReportInput(
        metrics=["sessions"],
        dimensions=[],
        date_ranges=[GoogleAnalyticsDateRange(start_date="yesterday", end_date="yesterday")],
    )

    result = await run_report(
        client,
        property_id="123",
        request=request,
        max_rows=1000,
        max_result_chars=16_000,
    )

    assert result["rows"] == []
    assert result["row_count"] == 0
    assert result["truncated"] is False
    assert result["metadata"]["empty_reason"] == "NO_DATA"


async def test_list_report_fields_filters_bounds_and_omits_deprecated_aliases() -> None:
    client = _Client(
        {
            "dimensions": [
                {
                    "apiName": "country",
                    "uiName": "Country",
                    "description": "Geographic country",
                    "category": "Geography",
                    "deprecatedApiNames": ["oldCountry"],
                },
                {
                    "apiName": "customEvent:plan",
                    "uiName": "Plan",
                    "description": "x" * 350,
                    "category": "Custom",
                    "customDefinition": True,
                },
            ],
            "metrics": [
                {
                    "apiName": "sessions",
                    "uiName": "Sessions",
                    "description": "Session count",
                    "category": "Session",
                    "type": "TYPE_INTEGER",
                },
                {
                    "apiName": "customEvent:score",
                    "uiName": "Plan score",
                    "description": "Score",
                    "category": "Custom",
                    "type": "TYPE_FLOAT",
                    "customDefinition": True,
                    "blockedReasons": ["NO_REVENUE_METRICS"],
                },
            ],
        }
    )

    result = await list_report_fields(
        client,
        property_id="123",
        search="plan",
        kind="both",
        custom_only=True,
        limit=1,
    )

    assert result["dimension_count"] == 1
    assert result["metric_count"] == 1
    assert result["truncated"] is False
    assert result["dimensions"][0]["api_name"] == "customEvent:plan"
    assert len(result["dimensions"][0]["description"]) == 300
    assert result["metrics"][0]["type"] == "TYPE_FLOAT"
    assert result["metrics"][0]["blocked_reasons"] == ["NO_REVENUE_METRICS"]
    assert "deprecatedApiNames" not in result["dimensions"][0]
    path, call = client.calls[0]
    assert path == "properties/123/metadata"
    assert call == {
        "operation": "list_report_fields",
        "policy": IntegrationRequestPolicy.READ,
    }


async def test_list_report_fields_reports_counts_before_per_kind_bound() -> None:
    client = _Client(
        {
            "dimensions": [
                {"apiName": "country", "uiName": "Country"},
                {"apiName": "city", "uiName": "City"},
            ],
            "metrics": [
                {"apiName": "sessions", "uiName": "Sessions", "type": "TYPE_INTEGER"},
                {"apiName": "totalUsers", "uiName": "Users", "type": "TYPE_INTEGER"},
            ],
        }
    )

    result = await list_report_fields(
        client,
        property_id="123",
        search=None,
        kind="both",
        custom_only=False,
        limit=1,
    )

    assert result["dimension_count"] == 2
    assert result["metric_count"] == 2
    assert len(result["dimensions"]) == len(result["metrics"]) == 1
    assert result["truncated"] is True


@pytest.mark.parametrize("operation", ["run_report", "list_report_fields"])
async def test_report_operations_fail_closed_on_non_object_response(operation: str) -> None:
    client = _Client([])
    with pytest.raises(IntegrationValidationError, match="invalid report"):
        if operation == "run_report":
            await run_report(
                client,
                property_id="123",
                request=GoogleAnalyticsRunReportInput(
                    metrics=["sessions"],
                    dimensions=[],
                    date_ranges=[
                        GoogleAnalyticsDateRange(
                            start_date="yesterday",
                            end_date="yesterday",
                        )
                    ],
                ),
                max_rows=1000,
                max_result_chars=16_000,
            )
        else:
            await list_report_fields(
                client,
                property_id="123",
                search=None,
                kind="both",
                custom_only=False,
                limit=50,
            )


async def test_run_report_applies_serialized_character_budget_to_rows() -> None:
    client = _Client(
        {
            "dimensionHeaders": [{"name": "pagePath"}],
            "metricHeaders": [{"name": "sessions", "type": "TYPE_INTEGER"}],
            "rows": [
                {
                    "dimensionValues": [{"value": "x" * 1200}],
                    "metricValues": [{"value": "1"}],
                }
            ],
            "rowCount": 1,
        }
    )
    result = await run_report(
        client,
        property_id="123",
        request=GoogleAnalyticsRunReportInput(
            metrics=["sessions"],
            dimensions=["pagePath"],
            date_ranges=[GoogleAnalyticsDateRange(start_date="yesterday", end_date="yesterday")],
        ),
        max_rows=1000,
        max_result_chars=1000,
    )

    assert result["rows"] == []
    assert result["row_count"] == 1
    assert result["truncated"] is True
    assert result["truncation_note"].startswith("Showing 0 of 1 rows")
    assert len(json.dumps(result, ensure_ascii=False, separators=(",", ":"))) <= 1000
