"""Custom conversion and custom event discovery, and account-scoped Insights naming."""

import json
from unittest.mock import AsyncMock

import pytest

from core.exceptions.integration import (
    IntegrationAuthError,
    IntegrationPermissionError,
    IntegrationReportTooLargeError,
    IntegrationValidationError,
)
from integrations.meta_ads.client import META_GRAPH_API_VERSION, MetaAdsClient
from integrations.meta_ads.operations.list_conversions import list_conversions
from integrations.meta_ads.operations.list_custom_conversions import list_custom_conversions
from integrations.meta_ads.operations.run_insights import run_insights
from integrations.meta_ads.tools.schemas.insights import MetaAdsInsightsInput
from services.integrations.report_results import ReportResultBudget


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


async def test_insights_resolves_once_preserving_all_numbers_and_dimensions():
    client = _client(
        {"data": [_row(), _row()]},
        {
            "data": [
                {"id": "123", "name": "Same", "is_archived": True},
                {"id": "456", "name": "Same"},
            ]
        },
    )
    result = await _report(client)
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


async def test_unresolved_names_keep_ids_metrics_and_safe_note():
    result = await _report(_client({"data": [_row()]}, {"data": []}))
    action = result.rows[0].actions["actions"][0]
    assert action.custom_conversion_id == "123" and action.custom_conversion_name is None
    assert action.value == 2 and any("unresolved" in note for note in result.notes)


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


async def test_insights_names_custom_events_without_a_lookup():
    row = {
        "date_start": "2026-09-01",
        "date_stop": "2026-09-02",
        "conversions": [
            {"action_type": "offsite_conversion.fb_pixel_custom.Menu View", "value": "8"},
            {"action_type": "contact_website", "value": "3"},
        ],
    }
    client = _client({"data": [row]})
    result = await run_insights(
        client,
        account_id="1",
        request=MetaAdsInsightsInput(
            fields=["conversions"], since="2026-09-01", until="2026-09-02"
        ),
        max_rows=100,
        poll_seconds=1,
    )
    event, standard = result.rows[0].actions["conversions"]
    assert (event.custom_event_name, event.value) == ("Menu View", 8)
    assert standard.custom_event_name is None
    assert client.graph_get.await_count == 1 and result.notes == []


async def test_listing_combines_definitions_and_recent_custom_events():
    client = _client(
        {"data": [{"id": "123", "name": "Lead"}, {"id": "456", "name": "Quiet"}]},
        {
            "data": [
                {
                    "date_start": "2026-07-03",
                    "date_stop": "2026-09-30",
                    "actions": [
                        {"action_type": "offsite_conversion.custom.123", "value": "4"},
                        {"action_type": "offsite_conversion.fb_pixel_custom", "value": "9"},
                    ],
                    "conversions": [
                        {
                            "action_type": "offsite_conversion.fb_pixel_custom.Menu View",
                            "value": "9",
                        },
                        {"action_type": "subscribe_website", "value": "2"},
                    ],
                }
            ]
        },
    )
    result = await list_conversions(
        client, account_id="1", limit=100, budget=ReportResultBudget("meta_ads", "test")
    )
    assert [(item.kind, item.name, item.recent_conversions) for item in result.conversions] == [
        ("custom_conversion", "Lead", 4),
        ("custom_conversion", "Quiet", None),
        ("custom_event", "Menu View", 9),
    ]
    assert result.conversions[2].action_type == "offsite_conversion.fb_pixel_custom.Menu View"
    assert (result.recent_since, result.recent_until) == ("2026-07-03", "2026-09-30")
    assert result.conversion_count == 3
    params = client.graph_get.call_args.kwargs["params"]
    assert client.graph_get.call_args.args == ("act_1/insights",)
    assert (params["level"], params["date_preset"]) == ("account", "last_90d")


async def test_listing_keeps_definitions_when_recent_delivery_is_unavailable():
    client = _client({"data": [{"id": "123", "name": "Lead"}]}, IntegrationValidationError("No"))
    result = await list_conversions(
        client, account_id="1", limit=100, budget=ReportResultBudget("meta_ads", "test")
    )
    assert [item.name for item in result.conversions] == ["Lead"]
    assert result.conversions[0].recent_conversions is None
    assert any("unavailable" in note for note in result.notes)


async def test_listing_keeps_custom_events_when_definitions_are_unavailable():
    events = {
        "data": [
            {
                "date_start": "2026-07-03",
                "date_stop": "2026-09-30",
                "conversions": [
                    {"action_type": "offsite_conversion.fb_pixel_custom.Menu View", "value": "9"}
                ],
            }
        ]
    }
    client = _client(IntegrationPermissionError("No"), events)
    result = await list_conversions(
        client, account_id="1", limit=100, budget=ReportResultBudget("meta_ads", "test")
    )
    assert [(item.kind, item.name) for item in result.conversions] == [
        ("custom_event", "Menu View")
    ]
    assert result.conversion_count == 1
    assert any("definitions are unavailable" in note for note in result.notes)


@pytest.mark.parametrize(
    "responses",
    [
        (IntegrationAuthError("Auth"), {"data": []}),
        (IntegrationPermissionError("No"), IntegrationValidationError("No")),
    ],
)
async def test_listing_fails_on_auth_or_when_no_source_is_readable(responses):
    with pytest.raises((IntegrationAuthError, IntegrationPermissionError)):
        await list_conversions(
            _client(*responses),
            account_id="1",
            limit=100,
            budget=ReportResultBudget("meta_ads", "test"),
        )
