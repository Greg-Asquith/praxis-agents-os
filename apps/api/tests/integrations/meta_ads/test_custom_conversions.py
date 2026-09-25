"""Custom conversion discovery and account-scoped Insights enrichment."""

import asyncio
import json
from unittest.mock import AsyncMock

import pytest
from pydantic_ai import ModelRetry

from core.exceptions.integration import (
    IntegrationAuthError,
    IntegrationConnectionError,
    IntegrationPermissionError,
    IntegrationRateLimitError,
    IntegrationReportTooLargeError,
    IntegrationTimeoutError,
    IntegrationValidationError,
)
from integrations.meta_ads.client import META_GRAPH_API_VERSION, MetaAdsClient
from integrations.meta_ads.operations.list_custom_conversions import list_custom_conversions
from integrations.meta_ads.operations.run_insights import run_insights
from integrations.meta_ads.tools.list_custom_conversions import meta_ads_list_custom_conversions
from integrations.meta_ads.tools.schemas.insights import MetaAdsInsightsInput
from services.integrations.http import IntegrationRequestPolicy
from services.integrations.report_results import ReportResultBudget


def _client(*responses):
    client = AsyncMock(spec=MetaAdsClient)
    client.graph_get.side_effect = responses
    return client


@pytest.mark.parametrize("limit", [0, 501, True, 1.5, "1"])
async def test_invalid_limit_fails_before_provider_access(limit):
    client = _client()
    with pytest.raises(IntegrationValidationError, match="limit"):
        await list_custom_conversions(client, account_id="1", limit=limit)
    with pytest.raises(ModelRetry, match="limit"):
        await meta_ads_list_custom_conversions(None, limit=limit)
    client.graph_get.assert_not_called()


def _paging(account="1", cursor="next"):
    return {
        "next": f"https://graph.facebook.com/{META_GRAPH_API_VERSION}/act_{account}/customconversions?after={cursor}"
    }


def _row():
    return {
        "date_start": "2026-09-01",
        "date_stop": "2026-09-02",
        **{
            field: [
                {
                    "action_type": "offsite_conversion.custom.123",
                    "value": value,
                    "1d_click": "1.5",
                    "action_device": "mobile",
                },
                {
                    "action_type": "offsite_conversion.custom.456",
                    "value": "7",
                    "action_device": "desktop",
                },
                {"action_type": "purchase", "value": "8"},
            ]
            for field, value in (
                ("actions", "2"),
                ("action_values", "5.75"),
                ("cost_per_action_type", "0.125"),
            )
        },
    }


async def _report(client, *, account_id="1", **kwargs):
    return await run_insights(
        client,
        account_id=account_id,
        request=MetaAdsInsightsInput(
            fields=["actions", "action_values", "cost_per_action_type"],
            since="2026-09-01",
            until="2026-09-02",
            attribution_windows=["1d_click"],
            action_breakdowns=["action_type", "action_device"],
        ),
        max_rows=100,
        poll_seconds=1,
        **kwargs,
    )


async def test_discovery_bounds_pagination_and_typed_metadata():
    client = _client(
        {
            "data": [{"id": "123", "name": "Same", "description": "x" * 600, "is_archived": True}],
            "paging": _paging(),
        },
        {
            "data": [{"id": "456", "name": "Same", "is_unavailable": True}],
            "paging": _paging(cursor="more"),
        },
    )
    result = await list_custom_conversions(client, account_id="1", limit=2)
    assert result.truncated and result.notes and result.conversion_count == 2
    first, second = result.conversions
    assert first.id != second.id and first.name == second.name
    assert first.is_archived and first.is_unavailable is None
    assert second.is_unavailable and second.description is None
    assert len(first.description) == 512
    calls = client.graph_get.call_args_list
    assert calls[1].kwargs["params"]["after"] == "next"
    assert calls[1].kwargs["params"]["limit"] == 1
    assert calls[0].kwargs["policy"] == IntegrationRequestPolicy.READ
    assert calls[1].kwargs["max_response_bytes"] < calls[0].kwargs["max_response_bytes"]


@pytest.mark.parametrize("paging", [_paging(account="2"), {"next": "https://example.com/?after=x"}])
async def test_discovery_rejects_cross_account_and_foreign_pagination(paging):
    with pytest.raises(IntegrationValidationError):
        await list_custom_conversions(
            _client({"data": [{"id": "123"}], "paging": paging}), account_id="1"
        )


async def test_discovery_page_cap_and_repeated_cursor():
    client = _client(
        *[{"data": [{"id": str(i)}], "paging": _paging(cursor=str(i))} for i in range(11)]
    )
    result = await list_custom_conversions(client, account_id="1")
    assert result.truncated and result.conversion_count == 10
    assert client.graph_get.await_count == 10
    repeated = _client(*[{"data": [{"id": "1"}], "paging": _paging()}] * 3)
    assert (await list_custom_conversions(repeated, account_id="1")).truncated
    assert repeated.graph_get.await_count == 2


@pytest.mark.parametrize(
    "row", [{"id": "../2"}, {"id": "3", "name": []}, {"id": "4", "is_archived": "false"}]
)
async def test_malformed_metadata_fails_discovery(row):
    with pytest.raises(IntegrationValidationError):
        await list_custom_conversions(_client({"data": [row]}), account_id="1")


async def test_metadata_missing_fields_are_null_and_empty_is_complete():
    result = await list_custom_conversions(_client({"data": [{"id": "123"}]}), account_id="1")
    assert result.conversions[0].name is None and result.conversions[0].is_archived is None
    empty = await list_custom_conversions(_client({"data": []}), account_id="1")
    assert empty.conversion_count == 0 and not empty.truncated


@pytest.mark.parametrize("background", [False, True])
async def test_insights_resolves_once_preserving_all_numbers_and_dimensions(background):
    responses = [
        {"data": [_row(), _row()]},
        {
            "data": [
                {"id": "123", "name": "Same", "is_archived": True},
                {"id": "456", "name": "Same"},
            ]
        },
    ]
    if background:
        responses = [
            IntegrationValidationError("Large", error_code="meta_ads_insights_too_large"),
            {"async_status": "Job Completed", "async_percent_completion": 100},
            *responses,
        ]
    client = _client(*responses)
    client.graph_post.return_value = {"report_run_id": "99"}
    result = await _report(client)
    assert result.mode == ("background" if background else "direct")
    for row in result.rows:
        for field, value in (
            ("actions", 2),
            ("action_values", 5.75),
            ("cost_per_action_type", 0.125),
        ):
            first, second, standard = row.actions[field]
            assert first.custom_conversion_id == "123" and first.custom_conversion_name == "Same"
            assert first.action_type == "offsite_conversion.custom.123"
            assert first.value == value and first.windows == {"1d_click": 1.5}
            assert first.breakdowns == {"action_device": "mobile"}
            assert second.custom_conversion_id == "456" and second.custom_conversion_name == "Same"
            assert second.value == 7 and second.breakdowns == {"action_device": "desktop"}
            assert standard.custom_conversion_id is None and standard.custom_conversion_name is None
    assert (
        sum(call.args == ("act_1/customconversions",) for call in client.graph_get.call_args_list)
        == 1
    )


@pytest.mark.parametrize(
    "metadata",
    [
        {"data": []},
        {"data": [{"id": "123", "is_archived": True}]},
        IntegrationPermissionError("private provider text"),
        IntegrationConnectionError("private provider text"),
        IntegrationValidationError("private provider text"),
    ],
)
async def test_unresolved_names_keep_ids_metrics_and_safe_note(metadata):
    result = await _report(_client({"data": [_row()]}, metadata))
    action = result.rows[0].actions["actions"][0]
    assert action.custom_conversion_id == "123" and action.custom_conversion_name is None
    assert action.value == 2 and any("unresolved" in note for note in result.notes)
    assert "private provider text" not in result.model_dump_json()


@pytest.mark.parametrize(
    "error",
    [
        IntegrationAuthError("Auth"),
        IntegrationRateLimitError("Wait"),
        IntegrationTimeoutError("Deadline"),
        asyncio.CancelledError(),
        TimeoutError(),
    ],
)
async def test_lookup_preserves_authentication_throttle_deadline_and_cancellation(error):
    with pytest.raises(type(error)):
        await _report(_client({"data": [_row()]}, error))


async def test_lookup_shares_report_byte_limit():
    report_payload = {"data": [_row()]}
    maximum = len(json.dumps(report_payload, separators=(",", ":")).encode()) + 20
    client = _client(report_payload, {"data": [{"id": "123", "name": "Long conversion name"}]})
    with pytest.raises(IntegrationReportTooLargeError):
        await _report(client, max_response_bytes=maximum)
    assert client.graph_get.call_args_list[1].kwargs["max_response_bytes"] == 20
    with pytest.raises(IntegrationReportTooLargeError):
        await list_custom_conversions(
            _client({"data": [{"id": "123"}]}),
            account_id="1",
            budget=ReportResultBudget("meta_ads", "test", maximum=1),
        )


async def test_partial_lookup_explains_unresolved_names():
    client = _client(
        {"data": [_row()]},
        *[
            {"data": [{"id": str(1000 + i), "name": "Other"}], "paging": _paging(cursor=str(i))}
            for i in range(10)
        ],
    )
    result = await _report(client)
    assert any("pagination limit" in note for note in result.notes)
    assert any("unresolved" in note for note in result.notes)
    assert result.rows[0].actions["actions"][0].value == 2


async def test_lookup_has_no_cross_account_or_cross_call_cache():
    for account_id, name in (
        ("1", "First account"),
        ("2", "Second account"),
        ("1", "Updated name"),
    ):
        client = _client({"data": [_row()]}, {"data": [{"id": "123", "name": name}]})
        result = await _report(client, account_id=account_id)
        assert result.rows[0].actions["actions"][0].custom_conversion_name == name
        assert client.graph_get.call_args.args == (f"act_{account_id}/customconversions",)
