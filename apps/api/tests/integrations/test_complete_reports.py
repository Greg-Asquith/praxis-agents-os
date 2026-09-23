"""Report retrieval retains every page before runtime previewing."""

from importlib import import_module
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from pydantic_ai import ModelRetry

from core.exceptions.integration import IntegrationValidationError
from core.settings import settings
from integrations.google_analytics.operations.list_report_fields import list_report_fields
from integrations.google_analytics.operations.run_realtime_report import run_realtime_report
from integrations.google_analytics.operations.run_report import run_report
from integrations.google_analytics.tools.schemas import (
    GoogleAnalyticsDateRange,
    GoogleAnalyticsRunRealtimeReportInput,
    GoogleAnalyticsRunReportInput,
)
from integrations.google_search_console.operations.query_search_analytics import (
    query_search_analytics,
)
from integrations.google_search_console.tools.schemas import GoogleSearchConsoleSearchAnalyticsInput
from tests.integrations.bigquery.test_bigquery_tools import _dry_run, _run_operation


def analytics_page(start, stop, total):
    return {
        "dimensionHeaders": [{"name": "country"}],
        "metricHeaders": [{"name": "activeUsers", "type": "TYPE_INTEGER"}],
        "rowCount": total,
        "rows": [
            {"dimensionValues": [{"value": str(index)}], "metricValues": [{"value": "1"}]}
            for index in range(start, stop)
        ],
    }


def analytics_request(**values):
    return GoogleAnalyticsRunReportInput(
        metrics=["activeUsers"],
        dimensions=["country"],
        date_ranges=[GoogleAnalyticsDateRange(start_date="28daysAgo", end_date="yesterday")],
        **values,
    )


async def test_analytics_fetches_all_pages_and_preserves_aggregates():
    pages = [analytics_page(0, 10_000, 10_001), analytics_page(10_000, 10_001, 10_001)]
    pages[0]["totals"] = [{"metricValues": [{"value": "10001"}]}]
    client = SimpleNamespace(data_post=AsyncMock(side_effect=pages))
    result = await run_report(client, property_id="123", request=analytics_request())
    assert len(result["rows"]) == result["row_count"] == 10_001
    assert result["rows"][-1]["country"] == "10000"
    assert result["totals"] == [{"country": "", "activeUsers": 10_001}]
    assert not result["truncated"]
    assert [call.kwargs["json"]["offset"] for call in client.data_post.await_args_list] == [
        0,
        10_000,
    ]
    assert client.data_post.await_args_list[1].kwargs["json"]["limit"] == 1


async def test_analytics_respects_requested_limit_and_offset():
    client = SimpleNamespace(data_post=AsyncMock(return_value=analytics_page(10, 12, 100)))
    result = await run_report(
        client, property_id="123", request=analytics_request(limit=2, offset=10)
    )
    assert [row["country"] for row in result["rows"]] == ["10", "11"]
    assert result["truncated"]
    assert client.data_post.await_count == 1
    assert client.data_post.await_args.kwargs["json"]["limit"] == 2


@pytest.mark.parametrize("failure", ["empty", "repeated", "changed"])
async def test_analytics_rejects_incomplete_or_inconsistent_pages(failure):
    first = analytics_page(0, 1, 3)
    second = analytics_page(1, 2, 3)
    if failure == "empty":
        second["rows"] = []
    elif failure == "repeated":
        second = first
    else:
        second["rowCount"] = 4
    client = SimpleNamespace(data_post=AsyncMock(side_effect=[first, second]))
    with pytest.raises(IntegrationValidationError):
        await run_report(client, property_id="123", request=analytics_request())
    assert client.data_post.await_count == 2


async def test_analytics_combined_pages_obey_file_byte_limit(monkeypatch):
    monkeypatch.setattr(settings, "MAX_FILE_SIZE_AGENT_FILE", 350)
    client = SimpleNamespace(
        data_post=AsyncMock(side_effect=[analytics_page(0, 1, 2), analytics_page(1, 2, 2)])
    )
    with pytest.raises(IntegrationValidationError, match="No partial report"):
        await run_report(client, property_id="123", request=analytics_request())


async def test_realtime_requests_provider_maximum_and_labels_provider_truncation():
    client = SimpleNamespace(data_post=AsyncMock(return_value=analytics_page(0, 1500, 250_001)))
    result = await run_realtime_report(
        client,
        property_id="123",
        request=GoogleAnalyticsRunRealtimeReportInput(
            metrics=["activeUsers"], dimensions=["country"]
        ),
    )
    assert client.data_post.await_args.kwargs["json"]["limit"] == 250_000
    assert len(result["rows"]) == 1500
    assert result["truncated"]
    assert "does not support pagination" in result["truncation_note"]


async def test_field_discovery_retains_all_matching_dimensions_and_metrics():
    fields = [{"apiName": f"field{index}"} for index in range(201)]
    client = SimpleNamespace(
        data_get=AsyncMock(return_value={"dimensions": fields, "metrics": fields})
    )
    result = await list_report_fields(
        client, property_id="123", search=None, kind="both", custom_only=False, limit=None
    )
    assert len(result["dimensions"]) == len(result["metrics"]) == 201
    assert not result["truncated"]


def search_page(start, stop):
    return {
        "responseAggregationType": "byProperty",
        "rows": [
            {"keys": [str(index)], "clicks": 1, "impressions": 2, "ctr": 0.5, "position": 1}
            for index in range(start, stop)
        ],
    }


@pytest.mark.parametrize("limit", [None, 25_001])
async def test_search_console_collects_pages_instead_of_capping_the_saved_result(limit):
    client = SimpleNamespace(
        webmasters_post=AsyncMock(side_effect=[search_page(0, 25_000), search_page(25_000, 25_001)])
    )
    request = GoogleSearchConsoleSearchAnalyticsInput(
        start_date="2026-08-01", end_date="2026-08-28", dimensions=["country"], row_limit=limit
    )
    result = await query_search_analytics(client, site_url="sc-domain:example.com", request=request)
    assert len(result["rows"]) == result["row_count"] == 25_001
    assert result["rows"][-1]["keys"]["country"] == "25000"
    assert result["truncated"] is (limit is not None)
    assert [call.kwargs["json"]["startRow"] for call in client.webmasters_post.await_args_list] == [
        0,
        25_000,
    ]


async def test_search_console_stops_on_repeated_page(monkeypatch):
    monkeypatch.setattr(
        import_module("integrations.google_search_console.operations.query_search_analytics"),
        "MAX_SEARCH_ANALYTICS_ROWS",
        2,
    )
    client = SimpleNamespace(webmasters_post=AsyncMock(return_value=search_page(0, 2)))
    with pytest.raises(IntegrationValidationError):
        await query_search_analytics(
            client,
            site_url="sc-domain:example.com",
            request=GoogleSearchConsoleSearchAnalyticsInput(
                start_date="2026-08-01", end_date="2026-08-28", dimensions=["country"]
            ),
        )
    assert client.webmasters_post.await_count == 2


def query_page(start, stop, token=None):
    return {
        "jobComplete": True,
        "jobReference": {"projectId": "analytics", "jobId": "job", "location": "EU"},
        "schema": {"fields": [{"name": "value"}]},
        "totalRows": "1500",
        "rows": [{"f": [{"v": str(index)}]} for index in range(start, stop)],
        "pageToken": token,
    }


async def test_bigquery_reads_all_pages_without_reexecuting_the_query():
    client = SimpleNamespace(
        post=AsyncMock(side_effect=[_dry_run(), query_page(0, 1000, "next")]),
        get=AsyncMock(return_value=query_page(1000, 1500)),
    )
    result = await _run_operation(client)
    assert len(result["rows"]) == result["total_rows"] == 1500
    assert result["rows"][-1] == {"value": "1499"}
    assert not result["truncated"]
    assert client.post.await_count == 2
    assert client.get.await_args.args == ("projects/analytics/queries/job",)
    assert client.get.await_args.kwargs["params"]["pageToken"] == "next"


@pytest.mark.parametrize("failure", ["repeated", "missing", "foreign_job"])
async def test_bigquery_rejects_incomplete_or_invalid_result_pages(failure):
    first = query_page(0, 1000, "next")
    second = query_page(1000, 1100, "next" if failure == "repeated" else None)
    if failure == "foreign_job":
        first["jobReference"]["projectId"] = "foreign"
    client = SimpleNamespace(
        post=AsyncMock(side_effect=[_dry_run(), first]), get=AsyncMock(return_value=second)
    )
    with pytest.raises(ModelRetry):
        await _run_operation(client)
    assert client.get.await_count == (0 if failure == "foreign_job" else 1)
