"""Complete report budgets cover every account and its normalised result."""

import asyncio
from importlib import import_module
from itertools import pairwise
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from pydantic_core import to_jsonable_python

from core.exceptions.integration import IntegrationAuthError, IntegrationReportTooLargeError
from core.settings import settings
from integrations.google_analytics.tools.schemas import GoogleAnalyticsDateRange
from services.agents.runtime.structured_results import result_json
from services.integrations.context.fan_out import run_context_fan_out
from services.integrations.context.results import serialize_fan_out_results
from services.integrations.report_results import ReportResultBudget
from tests.integrations.google_ads.test_tools_and_audits import _read_ctx, _read_entry
from tests.integrations.google_analytics.test_tools_and_audits import _entry as analytics_entry
from tests.integrations.google_search_console.test_tools_and_audits import _entry as search_entry
from tests.integrations.test_complete_reports import analytics_page
from tests.services.integrations.context.test_fan_out import _binding, _ctx, _entry


@pytest.fixture
def report_audit(monkeypatch):
    audit = AsyncMock()
    monkeypatch.setattr(
        "services.integrations.operations.record_integration_operation_audit_event", audit
    )
    return audit


@pytest.mark.parametrize(
    ("provider", "operation", "entry_factory", "method", "args", "payload"),
    [
        (
            "google_ads",
            "run_report",
            _read_entry,
            "post",
            {"query": "SELECT campaign.name FROM campaign"},
            [{"results": [{"campaign": {"name": "x" * 1_800}}]}],
        ),
        *[
            (
                "google_analytics",
                operation,
                analytics_entry,
                "data_post",
                {
                    "metrics": ["activeUsers"],
                    "dimensions": ["country"],
                    **(
                        {
                            "date_ranges": [
                                GoogleAnalyticsDateRange(
                                    start_date="2026-08-01", end_date="2026-08-28"
                                )
                            ]
                        }
                        if operation == "run_report"
                        else {}
                    ),
                },
                {
                    **analytics_page(0, 1, 1),
                    "rows": [
                        {
                            "dimensionValues": [{"value": "x" * 1_800}],
                            "metricValues": [{"value": "1"}],
                        }
                    ],
                },
            )
            for operation in ("run_report", "run_realtime_report")
        ],
        (
            "google_analytics",
            "list_report_fields",
            analytics_entry,
            "data_get",
            {},
            {"dimensions": [{"apiName": "country", "uiName": "x" * 1_800}], "metrics": []},
        ),
        (
            "google_search_console",
            "query_search_analytics",
            search_entry,
            "webmasters_post",
            {
                "start_date": "2026-08-01",
                "end_date": "2026-08-28",
                "dimensions": ["query"],
            },
            {
                "rows": [
                    {
                        "keys": ["x" * 1_800],
                        "clicks": 1,
                        "impressions": 2,
                        "ctr": 0.5,
                        "position": 1,
                    }
                ]
            },
        ),
    ],
)
@pytest.mark.parametrize("maximum", [3_000, 10_000])
async def test_report_tools_share_remaining_capacity_and_stop_on_aggregate_overflow(
    monkeypatch, report_audit, provider, operation, entry_factory, method, args, payload, maximum
):
    monkeypatch.setattr(settings, "MAX_FILE_SIZE_AGENT_FILE", maximum)
    module = import_module(f"integrations.{provider}.tools.{operation}")
    provider_call = AsyncMock(return_value=payload)
    monkeypatch.setattr(
        module,
        f"{provider}_client",
        AsyncMock(return_value=SimpleNamespace(**{method: provider_call})),
    )
    entries = tuple(
        entry_factory(
            f"sc-domain:example{index}.com" if provider == "google_search_console" else str(index)
        )
        for index in (111, 222, 333)
    )
    ctx = _read_ctx(*entries, tool_name=module.DEFINITION.name)

    if maximum == 3_000:
        with pytest.raises(IntegrationReportTooLargeError, match="No partial report"):
            await module.DEFINITION.function(ctx, **args)
        assert provider_call.await_count == 2
    else:
        result = await module.DEFINITION.function(ctx, **args)
        assert len(result["results"]) == provider_call.await_count == 3
        assert all(entry["status"] == "success" for entry in result["results"])
        assert len(result_json(to_jsonable_python(result)).encode()) < maximum
    limits = [call.kwargs["max_response_bytes"] for call in provider_call.await_args_list]
    assert limits[0] < maximum
    assert all(left > right for left, right in pairwise(limits))


async def test_later_account_pages_stop_before_another_page_or_account(monkeypatch, report_audit):
    monkeypatch.setattr(settings, "MAX_FILE_SIZE_AGENT_FILE", 6_000)
    module = import_module("integrations.google_analytics.tools.run_report")
    pages = [analytics_page(0, 1, 1), analytics_page(0, 1, 3), analytics_page(1, 2, 3)]
    for index, page in enumerate(pages):
        page["rows"][0]["dimensionValues"][0]["value"] = str(index) * (
            1_000 if index == 0 else 2_600
        )
    provider_call = AsyncMock(side_effect=pages)
    monkeypatch.setattr(
        module,
        "google_analytics_client",
        AsyncMock(return_value=SimpleNamespace(data_post=provider_call)),
    )
    ctx = _read_ctx(
        *(analytics_entry(str(index)) for index in (111, 222, 333)),
        tool_name=module.DEFINITION.name,
    )

    with pytest.raises(IntegrationReportTooLargeError, match="No partial report"):
        await module.DEFINITION.function(
            ctx,
            metrics=["activeUsers"],
            dimensions=["country"],
            date_ranges=[GoogleAnalyticsDateRange(start_date="2026-08-01", end_date="2026-08-28")],
        )

    assert provider_call.await_count == 3
    assert [call.args[0] for call in provider_call.await_args_list] == [
        "properties/111:runReport",
        "properties/222:runReport",
        "properties/222:runReport",
    ]
    assert report_audit.await_args.kwargs["status"] == "failure"
    assert report_audit.await_args.kwargs["error_code"] == "IntegrationReportTooLargeError"


async def test_budget_counts_error_envelopes_and_multibyte_account_metadata_exactly():
    entries = (_entry("Café"), _entry("Unavailable"), _entry("Three"))

    async def operation(entry):
        if entry == entries[1]:
            raise IntegrationAuthError("Reconnect the account.")
        return {"rows": [{"value": "£" * 50}]}

    expected = await run_context_fan_out(_ctx(entries), binding=_binding(), operation=operation)
    payload = {"results": serialize_fan_out_results(expected)}
    size = len(result_json(payload).encode())
    budget = ReportResultBudget("gmail", "test", maximum=size)
    actual = await run_context_fan_out(
        _ctx(entries), binding=_binding(), operation=operation, result_budget=budget
    )
    assert actual == expected
    assert budget.used == size
    with pytest.raises(IntegrationReportTooLargeError):
        await run_context_fan_out(
            _ctx(entries),
            binding=_binding(),
            operation=operation,
            result_budget=ReportResultBudget("gmail", "test", maximum=size - 1),
        )


async def test_budget_preserves_cancellation_and_stops_later_accounts():
    operation = AsyncMock(side_effect=asyncio.CancelledError)
    with pytest.raises(asyncio.CancelledError):
        await run_context_fan_out(
            _ctx((_entry("One"), _entry("Two"))),
            binding=_binding(),
            operation=operation,
            result_budget=ReportResultBudget("gmail", "test"),
        )
    assert operation.await_count == 1


async def test_budget_counts_authorisation_denials_before_later_accounts(report_audit):
    entries = (_entry("Read only", write_allowed=False), _entry("Writable"))
    operation = AsyncMock(return_value={"rows": []})
    with pytest.raises(IntegrationReportTooLargeError):
        await run_context_fan_out(
            _ctx(entries, tool_name="gmail_send_message"),
            binding=_binding(requires_write=True),
            operation=operation,
            result_budget=ReportResultBudget("gmail", "test", maximum=100),
        )
    operation.assert_not_awaited()
    assert report_audit.await_args.kwargs["error_code"] == "write_not_permitted"
