# apps/api/tests/integrations/meta_ads/test_budget_schedules.py

"""Meta budget increases: period rules, the account capability, stale budgets, and read-back."""

from datetime import UTC, datetime
from unittest.mock import AsyncMock
from zoneinfo import ZoneInfo

import httpx2
import pytest
from pydantic_ai import ModelRetry

from integrations.meta_ads.client import MetaAdsClient
from integrations.meta_ads.operations.budget_schedules import (
    MetaAdsExistingPeriod,
    add_periods,
    review_periods,
    schedule_problem,
)
from integrations.meta_ads.operations.list_objects import read_objects_by_id
from integrations.meta_ads.references import MetaAdsCampaignReference
from integrations.meta_ads.tools import schedule_budget_increases as tool
from integrations.meta_ads.tools.schemas.budget_schedules import (
    MetaAdsBudgetPeriod,
    MetaAdsBudgetScheduleOutput,
)
from tests.integrations.meta_ads.support import (
    FakeGraph,
    obj,
    static_token,
    write_tool_context,
)

ZONE = ZoneInfo("Europe/Paris")
NOW = datetime(2026, 11, 1, 12, tzinfo=UTC)
CAPABLE = {"capabilities": ["CAN_USE_BUDGET_SCHEDULING_API"]}
CAMPAIGN = MetaAdsCampaignReference(account_id="123", campaign_id="9", label="Spring")


def period(start, end, **increase):
    return MetaAdsBudgetPeriod(start=start, end=end, **(increase or {"increase_amount": "50"}))


def test_periods_follow_metas_length_overlap_and_ceiling_rules():
    existing = MetaAdsExistingPeriod(
        id="1",
        start=datetime(2026, 11, 27, tzinfo=ZONE),
        end=datetime(2026, 11, 28, tzinfo=ZONE),
        value_type="ABSOLUTE",
        value=5000,
    )

    reviews = review_periods(
        [
            period("2026-11-29T00:00", "2026-11-29T02:59"),
            period("2026-11-27T12:00", "2026-11-28T12:00"),
            period("2026-11-30T00:00", "2026-12-01T00:00", increase_amount="700.71"),
            period("2026-11-30T00:00", "2026-12-01T00:00", increase_percent=33),
            period("2026-11-30T06:00", "2026-11-30T12:00"),
        ],
        [existing],
        daily_budget="100.10",
        currency="EUR",
        zone=ZONE,
        now=NOW,
    )

    short, overlaps_existing, too_high, percent, overlaps_new = reviews
    assert "at least 3 hours" in short.problem
    assert "from 2026-11-27T00:00 to 2026-11-28T00:00" in overlaps_existing.problem
    # The daily budget plus the increase can be at most 8 times the daily budget.
    assert "at most 700.7 EUR" in too_high.problem
    # A percentage becomes a fixed amount of today's budget, rounded down to whole cents.
    assert percent.problem is None
    assert (percent.planned.increase_amount, percent.planned.increase_minor) == ("33.03", 3303)
    assert "from 2026-11-30T00:00 to 2026-12-01T00:00" in overlaps_new.problem


async def test_increases_need_a_daily_budget_held_by_the_object():
    graph = FakeGraph(
        [
            obj("9", "campaign", lifetime_budget="100000", budget_remaining="40000"),
            obj("8", "adset", campaign_id="7", daily_budget="1500"),
            obj("7", "campaign", daily_budget="5000"),
            obj("6", "adset", campaign_id="7", campaign={"daily_budget": "5000"}),
        ]
    )
    async with httpx2.AsyncClient(transport=httpx2.MockTransport(graph.handle)) as http:
        client = MetaAdsClient(static_token, client=http)
        campaigns = await read_objects_by_id(
            client, account_id="123", object_type="campaign", object_ids=["9", "7"], currency="EUR"
        )
        ad_sets = await read_objects_by_id(
            client, account_id="123", object_type="adset", object_ids=["8", "6"], currency="EUR"
        )

    assert "lifetime budget" in schedule_problem("campaign", campaigns["9"])
    assert schedule_problem("campaign", campaigns["7"]) is None
    assert schedule_problem("adset", ad_sets["8"]) is None
    assert "campaign's budget" in schedule_problem("adset", ad_sets["6"])


async def test_periods_are_sent_once_in_time_order_and_a_moved_period_stays_unverified():
    later, earlier = review_periods(
        [
            period("2026-12-24T00:00", "2026-12-26T00:00"),
            period("2026-11-27T00:00", "2026-11-30T00:00", increase_amount="25.50"),
        ],
        [],
        daily_budget="100",
        currency="EUR",
        zone=ZONE,
        now=NOW,
    )
    graph = FakeGraph([], post={"9": "shift_end"})

    async with httpx2.AsyncClient(transport=httpx2.MockTransport(graph.handle)) as http:
        ledger = await add_periods(
            MetaAdsClient(static_token, client=http),
            account_id="123",
            object_id="9",
            periods=[later.planned, earlier.planned],
        )

    assert graph.sent[0] == {
        "budget_value": "2550",
        "budget_value_type": "ABSOLUTE",
        "time_start": str(int(datetime(2026, 11, 27, tzinfo=ZONE).timestamp())),
        "time_end": str(int(datetime(2026, 11, 30, tzinfo=ZONE).timestamp())),
    }
    assert len(graph.sent) == 2
    assert [parent.outcome for parent in ledger.parents] == ["unverified", "unverified"]
    assert ledger.parents[0].effects[0].error_code == "PERIOD_NOT_CONFIRMED"


async def test_a_lost_reply_is_not_sent_again(monkeypatch):
    sleep = AsyncMock()
    monkeypatch.setattr("services.integrations.http.asyncio.sleep", sleep)
    [planned] = review_periods(
        [period("2026-11-27T00:00", "2026-11-30T00:00")],
        [],
        daily_budget="100",
        currency="EUR",
        zone=ZONE,
        now=NOW,
    )
    graph = FakeGraph([], post={"9": "timeout"})

    async with httpx2.AsyncClient(transport=httpx2.MockTransport(graph.handle)) as http:
        ledger = await add_periods(
            MetaAdsClient(static_token, client=http),
            account_id="123",
            object_id="9",
            periods=[planned.planned],
        )

    assert graph.posts == ["9"]
    sleep.assert_not_awaited()
    assert ledger.parents[0].outcome == "unverified"


def schedule_context(monkeypatch, http, *, proposed_periods=1, shown_budget="100"):
    async def client(_ctx, _entry):
        return MetaAdsClient(static_token, client=http)

    monkeypatch.setattr(tool, "meta_ads_client", client)
    proposed = {
        "campaign": CAMPAIGN.model_dump(mode="json"),
        "periods": [
            {"start": "2030-11-29T00:00", "end": "2030-12-02T00:00", "increase_percent": 50}
        ]
        * proposed_periods,
    }
    reviewed = {"_schedule_checks": {"unavailable": False, "daily_budget": shown_budget}}
    return write_tool_context(
        monkeypatch,
        http,
        tool_name="meta_ads_schedule_budget_increases",
        proposed=proposed,
        reviewed=reviewed,
        tool_modules=(tool,),
    )


async def schedule(ctx, *periods):
    return await tool.meta_ads_schedule_budget_increases(
        ctx,
        campaign=CAMPAIGN,
        periods=list(periods)
        or [period("2030-11-29T00:00", "2030-12-02T00:00", increase_percent=50)],
    )


async def test_tool_adds_a_percentage_increase_as_an_amount_and_reads_it_back(monkeypatch):
    graph = FakeGraph([obj("9", "campaign", daily_budget="10000")], account=CAPABLE)
    http = httpx2.AsyncClient(transport=httpx2.MockTransport(graph.handle))
    ctx, audit = schedule_context(monkeypatch, http)

    async with http:
        result = await schedule(ctx)

    MetaAdsBudgetScheduleOutput.model_validate(result)
    assert graph.sent[0]["budget_value"] == "5000"
    [row] = result["results"][0]["data"]["periods"]
    assert (row["outcome"], row["increase_amount"], row["start"]) == (
        "added",
        "50",
        "2030-11-29T00:00",
    )
    pending, terminal = (call.kwargs for call in audit.await_args_list)
    intent = pending["operation_detail"].intent_groups[0].items[0].fields
    assert (intent["daily_budget"], intent["increase_amount"], intent["increase_percent"]) == (
        "100",
        "50",
        "50",
    )
    assert terminal["status"] == "success"


async def test_an_account_without_the_capability_adds_nothing(monkeypatch):
    graph = FakeGraph([obj("9", "campaign", daily_budget="10000")], account={"capabilities": []})
    http = httpx2.AsyncClient(transport=httpx2.MockTransport(graph.handle))
    ctx, _audit = schedule_context(monkeypatch, http)

    async with http:
        result = await schedule(ctx)

    assert graph.posts == []
    assert "Ads Manager" in result["results"][0]["error_message"]


async def test_a_budget_changed_since_approval_adds_nothing(monkeypatch):
    graph = FakeGraph([obj("9", "campaign", daily_budget="10000")], account=CAPABLE)
    http = httpx2.AsyncClient(transport=httpx2.MockTransport(graph.handle))
    ctx, _audit = schedule_context(monkeypatch, http, shown_budget="80")

    async with http:
        result = await schedule(ctx)

    assert graph.posts == []
    assert "daily budget changed" in result["results"][0]["error_message"]


async def test_a_period_added_after_approval_is_refused(monkeypatch):
    graph = FakeGraph([obj("9", "campaign", daily_budget="10000")], account=CAPABLE)
    http = httpx2.AsyncClient(transport=httpx2.MockTransport(graph.handle))
    ctx, _audit = schedule_context(monkeypatch, http)

    async with http:
        with pytest.raises(ModelRetry, match="added after approval"):
            await schedule(
                ctx,
                period("2030-11-29T00:00", "2030-12-02T00:00"),
                period("2030-12-24T00:00", "2030-12-26T00:00"),
            )

    assert graph.posts == []
