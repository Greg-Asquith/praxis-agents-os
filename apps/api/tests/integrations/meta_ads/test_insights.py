"""Validate report bounds, numeric rows, paging, and background recovery."""

import importlib
import json
from datetime import date
from unittest.mock import AsyncMock

import httpx2
import pytest
from pydantic_ai import ModelRetry

from core.exceptions.integration import IntegrationReportTooLargeError, IntegrationValidationError
from integrations.meta_ads.client import META_GRAPH_API_VERSION, MetaAdsClient
from integrations.meta_ads.operations.run_insights import run_insights
from integrations.meta_ads.operations.values import numeric_value
from integrations.meta_ads.tools.utils.validation import months_before, validated_insights_request
from services.integrations.http import IntegrationRequestPolicy
from tests.integrations.meta_ads.support import static_token

module = importlib.import_module("integrations.meta_ads.operations.run_insights")
TODAY = date(2026, 9, 24)


def request(**changes):
    return validated_insights_request(
        max_rows=10_000,
        today=TODAY,
        **{
            "fields": ["spend", "impressions"],
            "since": "2026-09-01",
            "until": "2026-09-10",
            **changes,
        },
    )


def row(**changes):
    return {
        "account_id": "1",
        "account_name": "Account",
        "campaign_id": "2",
        "campaign_name": "Campaign",
        "date_start": "2026-09-01",
        "date_stop": "2026-09-10",
        "spend": "5339.5",
        "impressions": "12345",
        **changes,
    }


def client(*responses):
    result = AsyncMock(spec=MetaAdsClient)
    result.graph_get.side_effect = list(responses)
    return result


async def run(provider, query=None, **kwargs):
    return await run_insights(
        provider,
        account_id="1",
        request=query or request(),
        max_rows=10_000,
        poll_seconds=20,
        **kwargs,
    )


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"since": "last_week"}, "since"),
        ({"until": "20260910"}, "until"),
        ({"since": "2026-09-11"}, "since"),
    ],
)
def test_validation_names_rejected_argument(changes, message):
    with pytest.raises(ModelRetry, match=message):
        request(**changes)


def test_calendar_retention_boundaries():
    assert months_before(date(2024, 3, 31), 1) == date(2024, 2, 29)
    assert request(since="2023-08-24").since == "2023-08-24"
    assert request(since="2025-08-24", fields=["unique_clicks"])


def test_retained_metric_sort_is_rejected_with_old_breakdowns():
    with pytest.raises(ModelRetry, match="13 months"):
        request(
            since="2025-07-01",
            fields=["spend", "reach"],
            breakdowns=["age"],
            sort="reach_descending",
        )


async def test_every_parameter_and_action_window_is_preserved():
    provider = client(
        {
            "data": [
                row(
                    actions=[{"action_type": "purchase", "value": "4", "1d_click": "3"}],
                    age="25-34",
                    gender="female",
                    impressions="12345",
                )
            ]
        }
    )
    query = request(
        fields=["spend", "impressions", "actions"],
        breakdowns=["age", "gender"],
        action_breakdowns=["action_type"],
        attribution_windows=["1d_click"],
        time_increment=1,
        filters=[{"field": "campaign.id", "operator": "IN", "value": ["2"]}],
        sort="spend_descending",
        limit=5,
    )
    result = await run(provider, query)
    params = provider.graph_get.call_args.kwargs["params"]
    assert provider.graph_get.call_args.args == ("act_1/insights",)
    assert params["fields"].split(",") == [
        "spend",
        "impressions",
        "actions",
        "account_id",
        "account_name",
        "campaign_id",
        "campaign_name",
        "date_start",
        "date_stop",
        "account_currency",
    ]
    assert params["level"] == "campaign"
    assert json.loads(params["time_range"]) == {"since": query.since, "until": query.until}
    assert params["breakdowns"] == "age,gender"
    assert params["action_breakdowns"] == "action_type"
    assert params["time_increment"] == 1
    assert params["limit"] == 5
    assert json.loads(params["action_attribution_windows"]) == ["1d_click"]
    assert "use_unified_attribution_setting" not in params
    assert json.loads(params["filtering"]) == [
        {"field": "campaign.id", "operator": "IN", "value": ["2"]}
    ]
    assert json.loads(params["sort"]) == ["spend_descending"]
    assert result.rows[0].metrics == {"spend": 5339.5, "impressions": 12345}
    assert result.money_fields == ["spend"]
    assert type(result.rows[0].metrics["impressions"]) is int
    assert result.rows[0].keys["age"] == "25-34"
    assert result.rows[0].actions["actions"][0].model_dump() == {
        "action_type": "purchase",
        "custom_conversion_id": None,
        "custom_conversion_name": None,
        "custom_event_name": None,
        "value": 4.0,
        "windows": {"1d_click": 3.0},
        "breakdowns": {},
    }
    assert result.mode == "direct" and not result.truncated
    assert "override" in result.notes[0]


async def test_retention_drops_metrics_and_explains_adjustment(monkeypatch):
    class Clock:
        @staticmethod
        def now(_zone):
            class Day:
                @staticmethod
                def date():
                    return TODAY

            return Day()

    monkeypatch.setattr(module, "datetime", Clock)
    provider = client({"data": [row()]})
    result = await run(
        provider,
        request(
            since="2025-07-01", fields=["spend", "reach", "frequency", "cpp"], breakdowns=["age"]
        ),
    )
    params = provider.graph_get.call_args.kwargs["params"]
    assert not {"reach", "frequency", "cpp"}.intersection(params["fields"].split(","))
    assert result.rows[0].metrics == {"spend": 5339.5}
    assert "13 months" in result.notes[0]
    assert params["use_unified_attribution_setting"] == "true"


def next_page(cursor):
    return {
        "next": f"https://graph.facebook.com/{META_GRAPH_API_VERSION}/act_1/insights?after={cursor}"
    }


@pytest.mark.parametrize(
    "paging",
    [
        {"next": "https://example.com/?after=x"},
    ],
)
async def test_rejects_pagination_outside_account(paging):
    with pytest.raises(IntegrationValidationError, match="pagination"):
        await run(client({"data": [row()], "paging": paging}))


def too_large():
    return IntegrationValidationError("Too much data", error_code="meta_ads_insights_too_large")


@pytest.fixture
def fake_clock(monkeypatch):
    elapsed = [0.0]
    sleeps = []

    async def sleep(seconds):
        sleeps.append(seconds)
        elapsed[0] += seconds

    monkeypatch.setattr(module.time, "monotonic", lambda: elapsed[0])
    monkeypatch.setattr(module.asyncio, "sleep", sleep)
    return sleeps


async def test_background_completion_uses_read_policy_and_hides_job_id(fake_clock):
    provider = client(
        too_large(),
        {"async_status": "Job Running", "async_percent_completion": 50},
        {"async_status": "Job Completed", "async_percent_completion": 100},
        {"data": [row()]},
    )
    provider.graph_post.return_value = {"report_run_id": "987654321"}
    result = await run(provider)
    assert result.mode == "background"
    assert provider.graph_post.call_args.kwargs["policy"] == IntegrationRequestPolicy.READ
    assert (
        provider.graph_post.call_args.kwargs["data"]
        == provider.graph_get.call_args_list[0].kwargs["params"]
    )
    assert provider.graph_get.call_args_list[-1].args == ("987654321/insights",)
    assert provider.graph_get.call_args_list[1].kwargs["usage_account_id"] == "1"
    assert fake_clock == [1]
    assert "987654321" not in result.model_dump_json()


async def test_background_timeout_uses_bounded_backoff(fake_clock):
    provider = client(
        too_large(), *[{"async_status": "Job Running", "async_percent_completion": 100}] * 10
    )
    provider.graph_post.return_value = {"report_run_id": "99"}
    with pytest.raises(IntegrationValidationError, match="in time"):
        await run(provider)
    assert fake_clock == [1, 2, 4, 5, 5, 3]


async def test_background_report_read_error_is_not_a_correctable_request():
    def handler(request):
        if request.method == "POST":
            return httpx2.Response(200, json={"report_run_id": "99"}, request=request)
        if request.url.path.endswith("/act_1/insights"):
            error = {"code": 100, "error_subcode": 1487534, "message": "Too much data"}
        elif request.url.path.endswith("/99"):
            status = {"async_status": "Job Completed", "async_percent_completion": 100}
            return httpx2.Response(200, json=status, request=request)
        else:
            error = {"code": 100, "message": "Report unavailable"}
        return httpx2.Response(400, json={"error": error}, request=request)

    async with httpx2.AsyncClient(transport=httpx2.MockTransport(handler)) as http:
        with pytest.raises(IntegrationValidationError) as failure:
            await run(MetaAdsClient(static_token, client=http))
    assert failure.value.error_code != "meta_ads_invalid_insights"


async def test_byte_budget_stops_before_next_page():
    provider = client({"data": [row()], "paging": next_page("two")})
    with pytest.raises(IntegrationReportTooLargeError):
        await run(provider, max_response_bytes=20)
    assert provider.graph_get.await_count == 1


@pytest.mark.parametrize(
    "value",
    [
        "NaN",
        "Infinity",
    ],
)
def test_invalid_metrics_fail_instead_of_becoming_zero(value):
    with pytest.raises(IntegrationValidationError):
        numeric_value(value, operation="run_insights")


async def test_action_dimensions_and_unique_rates_keep_their_meaning():
    provider = client(
        {
            "data": [
                row(
                    unique_ctr="2.35",
                    unique_clicks="3",
                    actions=[
                        {"action_type": "purchase", "value": "2", "action_device": "mobile"},
                        {"action_type": "purchase", "value": "1", "action_device": "desktop"},
                    ],
                )
            ]
        }
    )
    result = await run(
        provider,
        request(
            fields=["unique_ctr", "unique_clicks", "actions"],
            action_breakdowns=["action_type", "action_device"],
        ),
    )
    assert result.rows[0].metrics == {"unique_ctr": 2.35, "unique_clicks": 3}
    assert [item.breakdowns for item in result.rows[0].actions["actions"]] == [
        {"action_device": "mobile"},
        {"action_device": "desktop"},
    ]


@pytest.mark.parametrize(
    "payload",
    [
        {"data": "invalid"},
        {"data": ["invalid"]},
    ],
)
async def test_malformed_provider_reports_fail(payload):
    with pytest.raises(IntegrationValidationError):
        await run(client(payload))


@pytest.mark.parametrize(
    "value",
    [
        "1e10000",
    ],
)
def test_count_exponents_are_bounded_before_integer_expansion(value):
    with pytest.raises(IntegrationValidationError, match="metric"):
        numeric_value(value, count=True, operation="run_insights")
