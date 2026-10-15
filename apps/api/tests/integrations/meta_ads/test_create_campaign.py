# apps/api/tests/integrations/meta_ads/test_create_campaign.py

"""Creating Meta campaigns: rules before approval, a dry run, one paused send, and proof after."""

from dataclasses import replace
from urllib.parse import parse_qsl

import httpx2
import pytest
from pydantic_ai import ModelRetry

from integrations.meta_ads.tools import create_campaign as tool_module
from integrations.meta_ads.tools.create_campaign import meta_ads_create_campaign
from integrations.meta_ads.tools.schemas.campaigns import (
    MetaAdsCreateCampaignOutput,
    MetaAdsCreateCampaignRequest,
)
from services.audit_events import AuditStatus
from tests.integrations.meta_ads.support import (
    FakeGraph,
    context_entry,
    obj,
    runtime_ctx,
    write_tool_context,
)


def args(**overrides) -> dict:
    values = {
        "name": "Spring launch",
        "objective": "sales",
        "budget": {"mode": "campaign_daily", "amount": "150"},
    }
    return {**values, **overrides}


class CampaignGraph(FakeGraph):
    """Serves the account and its campaigns, dry-runs campaigns, and creates them."""

    def __init__(self, *, behaviour="apply", account=None):
        super().__init__(
            [],
            account={
                "currency": "GBP",
                "timezone_name": "Europe/London",
                "min_daily_budget": 100,
                **(account or {}),
            },
        )
        self.behaviour = behaviour
        self.creates: list[dict[str, str]] = []

    def handle_post(self, request: httpx2.Request, object_id: str) -> httpx2.Response:
        form = dict(parse_qsl(request.content.decode()))
        if "execution_options" in form:
            self.dry_runs.append(form["name"])
            if self.behaviour == "reject_dry_run":
                error = {"code": 100, "error_user_msg": "Budget too low.", "fbtrace_id": "t"}
                return httpx2.Response(400, json={"error": error}, request=request)
            return httpx2.Response(200, json={"success": True}, request=request)
        self.creates.append(form)
        copies = 2 if self.behaviour == "lose_reply_twice" else 1
        for _ in range(copies):
            campaign_id = str(900 + len(self.objects) + 1)
            self.objects[campaign_id] = obj(
                campaign_id,
                "campaign",
                name=form["name"],
                objective=form["objective"],
                daily_budget=form.get("daily_budget"),
                bid_strategy=form["bid_strategy"],
                special_ad_categories=[],
                created_time="2099-01-01T00:00:00+0000",
            )
        if self.behaviour.startswith("lose_reply"):
            raise httpx2.ReadTimeout("lost", request=request)
        return httpx2.Response(200, json={"id": campaign_id}, request=request)


async def run_tool(monkeypatch, graph: CampaignGraph, values: dict, proposed: dict | None = None):
    http = httpx2.AsyncClient(transport=httpx2.MockTransport(graph.handle))
    ctx, audit = write_tool_context(
        monkeypatch, http, tool_name="meta_ads_create_campaign", proposed=proposed or values
    )
    request = MetaAdsCreateCampaignRequest.model_validate(values)
    async with http:
        result = await meta_ads_create_campaign(
            ctx, **{key: getattr(request, key) for key in values}
        )
    MetaAdsCreateCampaignOutput.model_validate(result)
    return result["results"][0], audit


async def test_a_campaign_is_dry_run_created_paused_once_and_read_back(monkeypatch):
    graph = CampaignGraph()

    entry, audit = await run_tool(monkeypatch, graph, args())

    (sent,) = graph.creates
    assert graph.dry_runs == ["Spring launch"]
    assert (sent["status"], sent["objective"], sent["daily_budget"], sent["bid_strategy"]) == (
        "PAUSED",
        "OUTCOME_SALES",
        "15000",
        "LOWEST_COST_WITHOUT_CAP",
    )
    # Meta refuses budget sharing alongside a campaign budget.
    assert "is_adset_budget_sharing_enabled" not in sent
    row = entry["data"]["campaign"]
    assert (row["outcome"], row["verified"], row["campaign_id"]) == ("created", True, "901")
    # The read-back reference is what meta_ads_create_ad_set takes.
    assert (row["campaign"]["campaign_id"], row["campaign"]["objective"]) == (
        "901",
        "OUTCOME_SALES",
    )
    pending = audit.await_args_list[0].kwargs["operation_detail"]
    fields = pending.intent_groups[0].items[0].fields
    assert (fields["daily_budget"], fields["budget_mode"]) == ("15000", "campaign_daily")


async def test_a_card_edit_of_status_objective_and_budget_is_sent_as_edited(monkeypatch):
    graph = CampaignGraph()
    edited = args(
        status="active",
        objective="traffic",
        budget={"mode": "ad_set", "share_between_ad_sets": True},
        special_ad_categories=[{"category": "housing", "countries": ["GB"]}],
    )

    await run_tool(monkeypatch, graph, edited, proposed=args())

    (sent,) = graph.creates
    assert (sent["status"], sent["objective"], sent["is_adset_budget_sharing_enabled"]) == (
        "ACTIVE",
        "OUTCOME_TRAFFIC",
        "true",
    )
    assert sent["special_ad_categories"] == '["HOUSING"]'


async def test_ad_set_budgets_send_the_sharing_choice_and_no_amount(monkeypatch):
    graph = CampaignGraph()
    budget = {"mode": "ad_set", "share_between_ad_sets": True}

    await run_tool(monkeypatch, graph, args(budget=budget))

    (sent,) = graph.creates
    assert sent["is_adset_budget_sharing_enabled"] == "true"
    assert "daily_budget" not in sent and "lifetime_budget" not in sent


async def test_a_lost_create_reply_is_settled_by_name_and_never_resent(monkeypatch):
    graph = CampaignGraph(behaviour="lose_reply")

    entry, _audit = await run_tool(monkeypatch, graph, args())

    row = entry["data"]["campaign"]
    assert len(graph.creates) == 1
    assert (row["outcome"], row["recovered"], row["campaign_id"]) == ("created", True, "901")


async def test_a_lost_create_reply_with_two_matches_is_unverified(monkeypatch):
    graph = CampaignGraph(behaviour="lose_reply_twice")

    entry, _audit = await run_tool(monkeypatch, graph, args())

    assert len(graph.creates) == 1
    assert entry["data"]["campaign"]["outcome"] == "unverified"


async def test_a_dry_run_rejection_creates_nothing_and_records_no_pending_event(monkeypatch):
    graph = CampaignGraph(behaviour="reject_dry_run")

    entry, audit = await run_tool(monkeypatch, graph, args())

    assert entry["status"] == "error"
    assert "Budget too low." in entry["error_message"]
    assert graph.creates == []
    assert all(call.kwargs["status"] != AuditStatus.PENDING for call in audit.await_args_list)


async def test_a_budget_below_the_account_minimum_is_refused_before_the_dry_run(monkeypatch):
    graph = CampaignGraph(account={"min_daily_budget": 20000})

    entry, _audit = await run_tool(monkeypatch, graph, args())

    assert entry["status"] == "error"
    assert "minimum daily budget for this ad account is 200 GBP" in entry["error_message"]
    assert graph.creates == graph.dry_runs == []


async def test_a_campaign_needs_exactly_one_writable_account_selected():
    selected = [replace(context_entry(account), write_allowed=True) for account in ("123", "456")]

    with pytest.raises(ModelRetry, match="exactly one writable"):
        await tool_module._validate_args(runtime_ctx(*selected), **args())


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        (
            {
                "budget": {"mode": "ad_set", "share_between_ad_sets": False},
                "bid_strategy": "roas_goal",
            },
            "needs a sales campaign with a campaign budget",
        ),
        (
            {
                "special_ad_categories": [
                    {"category": "issues_elections_politics", "countries": ["GB"]}
                ]
            },
            "Page authorisation",
        ),
    ],
)
async def test_rules_meta_would_refuse_are_refused_before_approval(overrides, message):
    entry = replace(context_entry("123"), write_allowed=True)

    with pytest.raises(ModelRetry, match=message):
        await tool_module._validate_args(runtime_ctx(entry), **args(**overrides))
