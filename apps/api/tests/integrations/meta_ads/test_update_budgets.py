"""Meta budget changes: routing to the budget's level, Meta's dry run, and read-back proof."""

import asyncio
from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import httpx2
import pytest

from integrations.meta_ads.client import MetaAdsClient
from integrations.meta_ads.models import MetaAdsObjectBudget
from integrations.meta_ads.operations import update_budgets as budgets_module
from integrations.meta_ads.operations.update_budgets import (
    budget_problem,
    budget_target,
    count_recent_budget_changes,
    read_budget_objects,
    update_budgets,
)
from integrations.meta_ads.references import MetaAdsAdSetReference, MetaAdsCampaignReference
from integrations.meta_ads.tools.schemas.activities import MetaAdsActivitiesData
from integrations.meta_ads.tools.schemas.budgets import MetaAdsBudgetOutput, MetaAdsBudgetUpdate
from integrations.meta_ads.tools.update_budgets import _account_checks, meta_ads_update_budgets
from services.integrations.context.domain import ResolvedActiveContext
from tests.integrations.meta_ads.support import FakeGraph, context_entry, obj, static_token


def problem(object_type, budget, amount, *, minimum=None, status="ACTIVE"):
    return budget_problem(
        object_type, status, budget, Decimal(amount), currency="EUR", min_daily_budget=minimum
    )


def test_budget_changes_go_to_the_level_that_holds_the_budget():
    campaign_budget = MetaAdsObjectBudget(
        kind="campaign", amount="50", remaining=None, period="daily"
    )
    own_budget = MetaAdsObjectBudget(kind="daily", amount="50", remaining=None)

    assert "Change the campaign" in problem("adset", campaign_budget, "60")
    assert "ad sets hold their own budgets" in problem("campaign", None, "60")
    assert problem("campaign", own_budget, "60") is None


def test_budget_floors_reject_below_minimum_and_below_spent():
    daily = MetaAdsObjectBudget(kind="daily", amount="50", remaining=None)
    lifetime = MetaAdsObjectBudget(kind="lifetime", amount="500", remaining="120.50")

    assert "minimum daily budget" in problem("adset", daily, "0.99", minimum="1.00")
    assert "already spent 379.50 EUR" in problem("adset", lifetime, "379.49")
    assert problem("adset", lifetime, "379.50") is None


async def test_decreases_go_first_and_a_disagreeing_read_back_stays_unverified():
    graph = FakeGraph(
        [
            obj("1", "adset", campaign_id="9", daily_budget="5000"),
            obj("2", "adset", campaign_id="9", daily_budget="5000"),
            obj("3", "adset", campaign_id="9", daily_budget="5000"),
        ],
        post={"1": "accept_without_change", "3": "apply_as_lifetime"},
    )
    async with httpx2.AsyncClient(transport=httpx2.MockTransport(graph.handle)) as http:
        client = MetaAdsClient(static_token, client=http)
        found = await read_budget_objects(
            client, account_id="123", currency="EUR", object_ids={"adset": ["1", "2", "3"]}
        )
        targets = [
            budget_target("adset", found["adset"]["1"], Decimal("60"), 6000),
            budget_target("adset", found["adset"]["2"], Decimal("40"), 4000),
            budget_target("adset", found["adset"]["3"], Decimal("70"), 7000),
        ]
        ledger = await update_budgets(client, account_id="123", currency="EUR", targets=targets)

    assert graph.posts == ["2", "1", "3"]
    raised, lowered, switched = ledger.parents
    assert lowered.outcome == "applied"
    assert raised.outcome == "unverified"
    assert raised.effects[0].error_code == "BUDGET_NOT_CONFIRMED"
    # The amount Meta still shows stays visible instead of reading like a failed read.
    assert dict(raised.effects[0].fields)["amount"] == "50"
    # A lifetime amount is never recorded as the daily budget that was requested.
    assert switched.outcome == "unverified"
    assert "amount" not in dict(switched.effects[0].fields)


async def test_ambiguous_budget_send_is_not_retried_and_throttle_is_failed(monkeypatch):
    sleep = AsyncMock()
    monkeypatch.setattr("services.integrations.http.asyncio.sleep", sleep)
    graph = FakeGraph(
        [
            obj("1", "adset", campaign_id="9", daily_budget="5000"),
            obj("2", "adset", campaign_id="9", daily_budget="5000"),
        ],
        post={"1": "timeout", "2": "throttle"},
    )
    async with httpx2.AsyncClient(transport=httpx2.MockTransport(graph.handle)) as http:
        client = MetaAdsClient(static_token, client=http)
        found = await read_budget_objects(
            client, account_id="123", currency="EUR", object_ids={"adset": ["1", "2"]}
        )
        targets = [
            budget_target("adset", found["adset"]["1"], Decimal("40"), 4000),
            budget_target("adset", found["adset"]["2"], Decimal("30"), 3000),
        ]
        ledger = await update_budgets(client, account_id="123", currency="EUR", targets=targets)

    assert graph.posts == ["1", "2"]
    sleep.assert_not_awaited()
    assert [parent.outcome for parent in ledger.parents] == ["unverified", "failed"]


async def test_cancelled_read_back_keeps_budgets_already_read():
    graph = FakeGraph(
        [
            obj("9", "campaign", daily_budget="5000"),
            obj("8", "adset", campaign_id="7", daily_budget="5000"),
        ]
    )

    def cancel_ad_set_read(request):
        if request.method == "GET" and request.url.path.endswith("/adsets") and graph.posts:
            raise asyncio.CancelledError
        return graph.handle(request)

    async with httpx2.AsyncClient(transport=httpx2.MockTransport(cancel_ad_set_read)) as http:
        client = MetaAdsClient(static_token, client=http)
        found = await read_budget_objects(
            client,
            account_id="123",
            currency="EUR",
            object_ids={"campaign": ["9"], "adset": ["8"]},
        )
        targets = [
            budget_target("campaign", found["campaign"]["9"], Decimal("60"), 6000),
            budget_target("adset", found["adset"]["8"], Decimal("60"), 6000),
        ]
        with pytest.raises(asyncio.CancelledError) as cancelled:
            await update_budgets(client, account_id="123", currency="EUR", targets=targets)

    campaign, ad_set = cancelled.value.ledger.parents
    assert campaign.outcome == "applied"
    assert dict(campaign.effects[0].fields)["amount"] == "60"
    assert ad_set.outcome == "unverified"


async def test_recent_changes_count_only_budget_events_in_the_last_hour():
    now = datetime(2026, 10, 2, 12, 0, tzinfo=UTC)
    graph = FakeGraph(
        [],
        activities=[
            {"event_type": "update_ad_set_budget", "event_time": "2026-10-02T11:30:00+0000"},
            {"event_type": "update_ad_set_budget", "event_time": "2026-10-02T10:59:00+0000"},
            {"event_type": "update_ad_set_run_status", "event_time": "2026-10-02T11:45:00+0000"},
            {"event_type": "update_ad_set_budget", "event_time": "2026-10-02T12:10:00+0000"},
        ],
    )
    for event in graph.activities:
        event["object_id"] = "8"

    async with httpx2.AsyncClient(transport=httpx2.MockTransport(graph.handle)) as http:
        counts = await count_recent_budget_changes(
            MetaAdsClient(static_token, client=http),
            account_id="123",
            timezone_name="Europe/Paris",
            object_ids=["8"],
            now=now,
        )

    assert counts.counts == {"8": 1}
    assert counts.complete


async def test_truncated_history_leaves_recent_changes_incomplete(monkeypatch):
    history = MetaAdsActivitiesData(
        events=[], event_count=0, truncated=True, window_note=None, timezone_name="UTC"
    )
    monkeypatch.setattr(budgets_module, "list_activities", AsyncMock(return_value=history))

    counts = await count_recent_budget_changes(
        AsyncMock(),
        account_id="123",
        timezone_name="UTC",
        object_ids=["8"],
        now=datetime(2026, 10, 2, 12, 0, tzinfo=UTC),
    )

    assert counts.counts == {"8": 0}
    assert not counts.complete


def tool_context(monkeypatch, graph: FakeGraph, http: httpx2.AsyncClient):
    pending_event_id = uuid4()
    audit = AsyncMock(return_value=pending_event_id)
    monkeypatch.setattr(
        "services.integrations.operations.record_integration_operation_audit_event", audit
    )

    async def client(_ctx, _entry):
        return MetaAdsClient(static_token, client=http)

    monkeypatch.setattr("integrations.meta_ads.tools.update_budgets.meta_ads_client", client)
    entry = replace(context_entry("123"), write_allowed=True)
    ctx = SimpleNamespace(
        deps=SimpleNamespace(
            active_context=ResolvedActiveContext(entries=(entry,)),
            workspace=SimpleNamespace(id=uuid4()),
            agent=SimpleNamespace(id=uuid4(), name="Ads agent"),
            run=SimpleNamespace(id=uuid4(), user_id=uuid4()),
        ),
        tool_name="meta_ads_update_budgets",
        tool_call_id="call-meta-budgets",
    )
    return ctx, audit


AD_SET = MetaAdsAdSetReference(account_id="123", campaign_id="9", adset_id="8", label="Prospecting")
CAMPAIGN = MetaAdsCampaignReference(account_id="123", campaign_id="9", label="Spring")


async def test_tool_checks_every_change_with_meta_then_sends_minor_units(monkeypatch):
    graph = FakeGraph(
        [
            obj("9", "campaign", lifetime_budget="100000", budget_remaining="40000"),
            obj("8", "adset", campaign_id="7", daily_budget="1500"),
        ],
        account={"min_daily_budget": "100"},
    )
    http = httpx2.AsyncClient(transport=httpx2.MockTransport(graph.handle))
    ctx, audit = tool_context(monkeypatch, graph, http)

    async with http:
        result = await meta_ads_update_budgets(
            ctx,
            updates=[
                MetaAdsBudgetUpdate(ad_set=AD_SET, amount="25.50"),
                MetaAdsBudgetUpdate(campaign=CAMPAIGN, amount="1200"),
            ],
        )

    MetaAdsBudgetOutput.model_validate(result)
    assert graph.dry_runs == ["8", "9"]
    assert graph.sent == [{"daily_budget": "2550"}, {"lifetime_budget": "120000"}]
    rows = {row["object_id"]: row for row in result["results"][0]["data"]["budgets"]}
    assert (rows["8"]["previous_amount"], rows["8"]["amount"], rows["8"]["outcome"]) == (
        "15",
        "25.5",
        "updated",
    )
    assert rows["9"]["outcome"] == "updated"
    pending, terminal = (call.kwargs for call in audit.await_args_list)
    ad_set_intent = pending["operation_detail"].intent_groups[0].items[0].fields
    assert ad_set_intent == {
        "object_id": "8",
        "object_name": "adset 8",
        "budget_kind": "daily",
        "previous_amount": "15",
        "requested_amount": "25.50",
        "currency": "EUR",
    }
    assert terminal["status"] == "success"


async def test_meta_dry_run_rejection_sends_nothing_and_keeps_metas_reason(monkeypatch):
    graph = FakeGraph(
        [obj("8", "adset", campaign_id="7", daily_budget="1500")],
        post={"8": "reject_dry_run"},
    )
    http = httpx2.AsyncClient(transport=httpx2.MockTransport(graph.handle))
    ctx, _audit = tool_context(monkeypatch, graph, http)

    async with http:
        result = await meta_ads_update_budgets(
            ctx, updates=[MetaAdsBudgetUpdate(ad_set=AD_SET, amount="2")]
        )

    entry = result["results"][0]
    assert graph.dry_runs == ["8"] and graph.posts == []
    assert entry["status"] == "error"
    assert "The budget is too low." in entry["error_message"]


async def test_tool_sends_nothing_when_a_dry_run_is_not_confirmed(monkeypatch):
    graph = FakeGraph(
        [
            obj("9", "campaign", daily_budget="5000"),
            obj("8", "adset", campaign_id="7", daily_budget="1500"),
        ],
        post={"8": "unconfirmed_dry_run"},
    )
    http = httpx2.AsyncClient(transport=httpx2.MockTransport(graph.handle))
    ctx, _audit = tool_context(monkeypatch, graph, http)

    async with http:
        result = await meta_ads_update_budgets(
            ctx,
            updates=[
                MetaAdsBudgetUpdate(campaign=CAMPAIGN, amount="60"),
                MetaAdsBudgetUpdate(ad_set=AD_SET, amount="20"),
            ],
        )

    assert graph.dry_runs == ["9", "8"] and graph.posts == []
    assert result["results"][0]["status"] == "error"


async def test_approval_checks_show_precision_and_dry_run_problems_before_approval():
    graph = FakeGraph([], post={"7": "reject_dry_run"}, account={"currency": "JPY"})
    entry = replace(
        context_entry("123"), permissions_metadata={"currency": "JPY", "timezone_name": "UTC"}
    )

    def ad_set(adset_id):
        return {
            "account_id": "123",
            "adset_id": adset_id,
            "status": "ACTIVE",
            "budget": {"kind": "daily", "amount": "1500", "remaining": None},
        }

    async with httpx2.AsyncClient(transport=httpx2.MockTransport(graph.handle)) as http:
        checks = await _account_checks(
            MetaAdsClient(static_token, client=http),
            entry,
            [("adset", ad_set("8"), "1000.5"), ("adset", ad_set("7"), "1000")],
        )

    # The fractional yen amount never reaches Meta; the other change is checked without being made.
    assert graph.dry_runs == ["7"] and graph.posts == []
    assert checks["8"]["problem"] is not None
    assert "The budget is too low." in checks["7"]["problem"]
