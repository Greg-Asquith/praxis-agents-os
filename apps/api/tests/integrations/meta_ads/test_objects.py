"""Check object filters, exact account-scoped reads, budgets and result limits."""

import json
from unittest.mock import AsyncMock

import pytest
from pydantic_ai import ModelRetry

from core.exceptions.integration import IntegrationValidationError
from integrations.meta_ads.client import MetaAdsClient
from integrations.meta_ads.operations.list_objects import list_objects
from integrations.meta_ads.tools.list_objects import meta_ads_list_objects
from services.integrations.http import IntegrationRequestPolicy


def provider(*pages):
    client = AsyncMock(spec=MetaAdsClient)
    client.graph_get.side_effect = pages
    return client


def page(*rows, cursor=None, edge="campaigns"):
    result = {"data": list(rows)}
    if cursor is not None:
        result["paging"] = {
            "next": f"https://graph.facebook.com/v26.0/act_123/{edge}?after={cursor}"
        }
    return result


async def read(client, **changes):
    return await list_objects(
        client, account_id="123", currency="EUR", **{"object_type": "campaign", **changes}
    )


@pytest.mark.parametrize(
    "object_type,expected",
    [
        ("campaign", ["ACTIVE", "PAUSED"]),
    ],
)
async def test_default_statuses_and_account_edge(object_type, expected):
    client = provider(page({"id": "10"}))
    result = await read(client, object_type=object_type)
    call = client.graph_get.call_args
    assert (
        call.args[0]
        == f"act_123/{ {'campaign': 'campaigns', 'adset': 'adsets', 'ad': 'ads'}[object_type] }"
    )
    assert call.kwargs["policy"] is IntegrationRequestPolicy.READ
    assert json.loads(call.kwargs["params"]["filtering"]) == [
        {"field": "effective_status", "operator": "IN", "value": expected}
    ]
    assert result.object_count == 1
    assert not result.truncated


async def test_all_explicit_filters_and_exact_id_lookup():
    client = provider(page({"id": "10"}, {"id": "11"}, edge="ads"))
    result = await read(
        client,
        object_type="ad",
        object_ids=["10"],
        statuses=["PAUSED"],
        campaign_ids=["20"],
        adset_ids=["30"],
        name_contains="Summer",
    )
    assert json.loads(client.graph_get.call_args.kwargs["params"]["filtering"]) == [
        {"field": "effective_status", "operator": "IN", "value": ["PAUSED"]},
        {"field": "id", "operator": "IN", "value": ["10"]},
        {"field": "campaign.id", "operator": "IN", "value": ["20"]},
        {"field": "adset.id", "operator": "IN", "value": ["30"]},
        {"field": "name", "operator": "CONTAIN", "value": "Summer"},
    ]
    assert [item.id for item in result.objects] == ["10"]


async def test_exact_ids_include_archived_objects_without_default_status_exclusion():
    client = provider(page({"id": "10", "effective_status": "ARCHIVED"}))
    result = await read(client, object_ids=["10"])
    statuses = json.loads(client.graph_get.call_args.kwargs["params"]["filtering"])[0]["value"]
    assert "ARCHIVED" in statuses and "DELETED" in statuses
    assert result.objects[0].effective_status == "ARCHIVED"


@pytest.mark.parametrize(
    "changes,message",
    [
        ({"statuses": ["CAMPAIGN_PAUSED"]}, "statuses"),
        ({"statuses": []}, "statuses"),
        ({"adset_ids": ["1"]}, "adset_ids"),
    ],
)
async def test_invalid_arguments_fail_before_context_or_provider(changes, message):
    with pytest.raises(ModelRetry, match=message):
        await meta_ads_list_objects(None, **{"object_type": "campaign", **changes})


@pytest.mark.parametrize("currency,amount", [("EUR", "123.45"), ("JPY", "12345")])
async def test_daily_and_lifetime_budgets_use_currency_offset(currency, amount):
    client = provider(
        page(
            {"id": "10", "daily_budget": "12345", "budget_remaining": "100"},
            {"id": "11", "daily_budget": "0", "lifetime_budget": "12345"},
        )
    )
    result = await list_objects(client, account_id="123", object_type="campaign", currency=currency)
    assert result.objects[0].budget.kind == "daily"
    assert result.objects[0].budget.amount == amount
    assert result.objects[1].budget.kind == "lifetime"
    assert result.objects[1].budget.amount == amount


async def test_campaign_held_budget_bid_schedule_and_parent_ids():
    client = provider(
        page(
            {
                "id": "10",
                "campaign_id": "20",
                "name": "x" * 700,
                "daily_budget": "0",
                "lifetime_budget": "0",
                "bid_amount": "123",
                "optimization_goal": "OFFSITE_CONVERSIONS",
                "bid_strategy": "COST_CAP",
                "start_time": "2026-09-01T00:00:00+0100",
                "end_time": "2026-09-30T00:00:00+0100",
            },
            edge="adsets",
        )
    )
    result = await read(client, object_type="adset")
    obj = result.objects[0]
    assert obj.budget.model_dump() == {"kind": "campaign", "amount": None, "remaining": None}
    assert obj.bid_amount == "1.23"
    assert obj.campaign_id == "20"
    assert len(obj.name) == 512
    assert obj.start_time == "2026-09-01T00:00:00+01:00"
    assert obj.end_time == "2026-09-30T00:00:00+01:00"
    assert obj.optimization_goal == "OFFSITE_CONVERSIONS"


async def test_paging_limit_truncation_and_cumulative_byte_budget():
    client = provider(page({"id": "10"}, cursor="one"), page({"id": "11"}, {"id": "12"}))
    result = await read(client, limit=2)
    assert result.truncated and result.object_count == 2
    calls = client.graph_get.call_args_list
    assert calls[1].kwargs["params"]["after"] == "one"
    assert calls[1].kwargs["params"]["limit"] == 1
    assert calls[1].kwargs["max_response_bytes"] < calls[0].kwargs["max_response_bytes"]


@pytest.mark.parametrize(
    "payload",
    [
        {"data": {}},
        {"data": ["bad"]},
    ],
)
async def test_malformed_provider_rows_are_rejected(payload):
    with pytest.raises(IntegrationValidationError):
        await read(provider(payload))


async def test_unsafe_cursor_url_is_rejected():
    with pytest.raises(IntegrationValidationError):
        await read(
            provider(
                {"data": [{"id": "1"}], "paging": {"next": "https://example.com/?after=token"}}
            )
        )
