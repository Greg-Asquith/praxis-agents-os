"""Custom conversion discovery and account-scoped Insights enrichment."""

import json
from unittest.mock import AsyncMock

import pytest

from core.exceptions.integration import (
    IntegrationAuthError,
    IntegrationReportTooLargeError,
    IntegrationValidationError,
)
from integrations.meta_ads.client import META_GRAPH_API_VERSION, MetaAdsClient
from integrations.meta_ads.operations.list_custom_conversions import list_custom_conversions
from integrations.meta_ads.operations.run_insights import run_insights
from integrations.meta_ads.tools.schemas.insights import MetaAdsInsightsInput


def _client(*responses):
    client = AsyncMock(spec=MetaAdsClient)
    client.graph_get.side_effect = responses
    return client


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


@pytest.mark.parametrize("paging", [_paging(account="2"), {"next": "https://example.com/?after=x"}])
async def test_discovery_rejects_cross_account_and_foreign_pagination(paging):
    with pytest.raises(IntegrationValidationError):
        await list_custom_conversions(
            _client({"data": [{"id": "123"}], "paging": paging}), account_id="1"
        )


@pytest.mark.parametrize(
    "background",
    [
        False,
    ],
)
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
    ],
)
async def test_unresolved_names_keep_ids_metrics_and_safe_note(metadata):
    result = await _report(_client({"data": [_row()]}, metadata))
    action = result.rows[0].actions["actions"][0]
    assert action.custom_conversion_id == "123" and action.custom_conversion_name is None
    assert action.value == 2 and any("unresolved" in note for note in result.notes)
    assert "private provider text" not in result.model_dump_json()


async def test_lookup_preserves_authentication_errors():
    with pytest.raises(IntegrationAuthError):
        await _report(_client({"data": [_row()]}, IntegrationAuthError("Auth")))


async def test_lookup_shares_report_byte_limit():
    report_payload = {"data": [_row()]}
    maximum = len(json.dumps(report_payload, separators=(",", ":")).encode()) + 20
    client = _client(report_payload, {"data": [{"id": "123", "name": "Long conversion name"}]})
    with pytest.raises(IntegrationReportTooLargeError):
        await _report(client, max_response_bytes=maximum)
    assert client.graph_get.call_args_list[1].kwargs["max_response_bytes"] == 20


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
