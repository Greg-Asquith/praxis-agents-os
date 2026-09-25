"""Check object filters, exact account-scoped reads, budgets and result limits."""

import json
from unittest.mock import AsyncMock

import pytest
from pydantic import ValidationError
from pydantic_ai import ModelRetry

from core.exceptions.integration import IntegrationReportTooLargeError, IntegrationValidationError
from integrations.meta_ads.client import MetaAdsClient
from integrations.meta_ads.operations.list_objects import list_objects
from integrations.meta_ads.tools.list_objects import meta_ads_list_objects
from integrations.meta_ads.tools.schemas.objects import MetaAdsObjectsInput
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
        ("adset", ["ACTIVE", "PAUSED", "CAMPAIGN_PAUSED"]),
        ("ad", ["ACTIVE", "PAUSED", "CAMPAIGN_PAUSED", "ADSET_PAUSED"]),
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
        ({"campaign_ids": ["1"]}, "campaign_ids"),
        ({"object_type": "ad", "campaign_ids": ["x"]}, "campaign_ids"),
        ({"object_type": "ad", "campaign_ids": ["1"] * 51}, "campaign_ids"),
        ({"limit": 501}, "limit"),
        ({"limit": 0}, "limit"),
        ({"limit": True}, "limit"),
        ({"name_contains": "x" * 513}, "name_contains"),
    ],
)
async def test_invalid_arguments_fail_before_context_or_provider(changes, message):
    with pytest.raises(ModelRetry, match=message):
        await meta_ads_list_objects(None, **{"object_type": "campaign", **changes})


def test_type_specific_delivery_status_sets():
    assert MetaAdsObjectsInput(object_type="adset", statuses=["CAMPAIGN_PAUSED"])
    assert MetaAdsObjectsInput(object_type="ad", statuses=["DISAPPROVED"])
    with pytest.raises(ValidationError, match="statuses"):
        MetaAdsObjectsInput(object_type="adset", statuses=["DISAPPROVED"])


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


async def test_campaign_stop_time_and_ad_budget():
    campaign = await read(provider(page({"id": "10", "stop_time": "2026-10-01T00:00:00-0700"})))
    ad = await read(provider(page({"id": "10", "adset_id": "30"}, edge="ads")), object_type="ad")
    assert campaign.objects[0].end_time == "2026-10-01T00:00:00-07:00"
    assert ad.objects[0].budget is None
    assert ad.objects[0].adset_id == "30"


async def test_paging_limit_truncation_and_cumulative_byte_budget():
    client = provider(page({"id": "10"}, cursor="one"), page({"id": "11"}, {"id": "12"}))
    result = await read(client, limit=2)
    assert result.truncated and result.object_count == 2
    calls = client.graph_get.call_args_list
    assert calls[1].kwargs["params"]["after"] == "one"
    assert calls[1].kwargs["params"]["limit"] == 1
    assert calls[1].kwargs["max_response_bytes"] < calls[0].kwargs["max_response_bytes"]


async def test_ten_page_cap():
    client = provider(*(page({"id": str(index)}, cursor=str(index)) for index in range(12)))
    result = await read(client, limit=500)
    assert client.graph_get.await_count == 10
    assert result.object_count == 10
    assert result.truncated


@pytest.mark.parametrize(
    "pages,count",
    [
        ([page({"id": "10"}, cursor="same"), page({"id": "11"}, cursor="same")], 2),
        ([page(cursor="one")], 1),
    ],
)
async def test_repeated_cursor_and_empty_page_stop(pages, count):
    client = provider(*pages)
    assert (await read(client)).truncated
    assert client.graph_get.await_count == count


@pytest.mark.parametrize(
    "payload",
    [
        {"data": {}},
        {"data": ["bad"]},
        {"data": [], "paging": []},
        {"data": [{"id": "not-digits"}]},
        {"data": [{"id": "1", "start_time": "next Tuesday"}]},
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


async def test_response_budget_overflow_stops_before_next_page():
    client = provider(page({"id": "10"}, cursor="one"))
    with pytest.raises(IntegrationReportTooLargeError):
        await read(client, max_response_bytes=10)
    assert client.graph_get.await_count == 1


@pytest.mark.parametrize("ids", [["../other"], ["1"] * 51])
async def test_internal_exact_ids_are_validated(ids):
    client = provider(page())
    with pytest.raises(IntegrationValidationError):
        await read(client, object_ids=ids)
    client.graph_get.assert_not_awaited()
