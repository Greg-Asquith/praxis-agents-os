# apps/api/tests/integrations/meta_ads/test_update_campaigns.py

"""Campaign setting edits: Meta's rules before approval, ad set bids, and read-back proof."""

import json
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import AsyncMock
from urllib.parse import parse_qsl
from uuid import uuid4

import httpx2
import pytest
from pydantic_ai import ModelRetry

from integrations.meta_ads.client import MetaAdsClient
from integrations.meta_ads.operations.edit_campaign import edit_problems
from integrations.meta_ads.references import MetaAdsAdSetReference, MetaAdsCampaignReference
from integrations.meta_ads.tools import update_campaigns as tool_module
from integrations.meta_ads.tools.schemas.campaign_edits import (
    MetaAdsCampaignEdit,
    MetaAdsUpdateCampaignsOutput,
    MetaAdsUpdateCampaignsRequest,
)
from integrations.meta_ads.tools.schemas.objects import MetaAdsObject
from services.integrations.context.domain import ResolvedActiveContext
from tests.integrations.meta_ads.support import FakeGraph, context_entry, obj, static_token


class CampaignGraph(FakeGraph):
    """Applies posted campaign settings the way Meta stores them, and reports lifetime spend."""

    def __init__(self, objects, *, spend=None, **kwargs):
        super().__init__(objects, **kwargs)
        self.spend = spend or {}

    def handle(self, request):
        if request.url.path.endswith("/insights"):
            rows = [{"campaign_id": key, "spend": value} for key, value in self.spend.items()]
            return httpx2.Response(200, json={"data": rows}, request=request)
        return super().handle(request)

    def handle_post(self, request, object_id):
        response = super().handle_post(request, object_id)
        form = dict(parse_qsl(request.content.decode()))
        if "execution_options" in form or self.post.get(object_id, "apply") != "apply":
            return response
        item = self.objects[object_id]
        for key in ("name", "spend_cap", "bid_strategy"):
            if key in form:
                item[key] = form[key]
        for adset_id, bid in json.loads(form.get("adset_bid_amounts", "{}")).items():
            self.objects[adset_id]["bid_amount"] = str(bid)
        return response


def _campaign(campaign_id="9", **fields):
    defaults = {
        "status": "ACTIVE",
        "daily_budget": "10000",
        "bid_strategy": "LOWEST_COST_WITHOUT_CAP",
    }
    return obj(campaign_id, "campaign", **{**defaults, **fields})


def _ad_set(adset_id, campaign_id="9", **fields):
    return obj(adset_id, "adset", campaign_id=campaign_id, **{"status": "ACTIVE", **fields})


def _reference(campaign_id="9", account_id="123") -> MetaAdsCampaignReference:
    return MetaAdsCampaignReference(
        account_id=account_id, campaign_id=campaign_id, label=f"Campaign {campaign_id}"
    )


def _bid(adset_id, amount, campaign_id="9"):
    return {
        "ad_set": MetaAdsAdSetReference(
            account_id="123", campaign_id=campaign_id, adset_id=adset_id, label=f"Ad set {adset_id}"
        ),
        "bid_amount": amount,
    }


def _edit(campaign_id="9", **settings) -> MetaAdsCampaignEdit:
    return MetaAdsCampaignEdit(campaign=_reference(campaign_id), **settings)


def _proposed(*edits: MetaAdsCampaignEdit) -> dict:
    return {"changes": [edit.model_dump(mode="json", exclude_none=True) for edit in edits]}


def _tool_context(monkeypatch, http, *, proposed, checks):
    audit = AsyncMock(return_value=uuid4())
    monkeypatch.setattr(
        "services.integrations.operations.record_integration_operation_audit_event", audit
    )
    monkeypatch.setattr(
        "integrations.meta_ads.operations.update_fields.checkpoint_integration_operation",
        AsyncMock(),
    )

    async def client(_ctx, _entry):
        return MetaAdsClient(static_token, client=http)

    monkeypatch.setattr(tool_module, "meta_ads_client", client)
    monkeypatch.setattr(tool_module, "proposed_args", lambda _ctx: proposed)
    monkeypatch.setattr(tool_module, "approved_display_args", lambda _ctx: {"_checks": checks})
    entry = replace(context_entry("123"), write_allowed=True)
    ctx = SimpleNamespace(
        deps=SimpleNamespace(
            active_context=ResolvedActiveContext(entries=(entry,)),
            workspace=SimpleNamespace(id=uuid4()),
            agent=SimpleNamespace(id=uuid4(), name="Ads agent"),
            run=SimpleNamespace(id=uuid4(), user_id=uuid4()),
        ),
        tool_name="meta_ads_update_campaigns",
        tool_call_id="call-meta-campaigns",
    )
    return ctx, audit


async def test_one_approval_lowers_a_limit_renames_and_moves_to_a_cost_goal_with_bids(
    monkeypatch,
):
    graph = CampaignGraph(
        [
            _campaign("9", spend_cap="80000"),
            _campaign("6"),
            _campaign("5"),
            _ad_set("51", campaign_id="5"),
            _ad_set("52", campaign_id="5", status="PAUSED"),
        ],
        spend={"9": "312.40"},
        account={"min_campaign_group_spend_cap": "10000"},
    )
    edits = [
        _edit("9", spend_limit="500"),
        _edit("6", name="Spring sale"),
        _edit(
            "5",
            bid_strategy="cost_per_result_goal",
            ad_set_bids=[_bid("51", "12", "5"), _bid("52", "9.50", "5")],
        ),
    ]
    checks = {
        "9": {"before": {"spend_limit": "800"}},
        "6": {"before": {"name": "campaign 6"}},
        "5": {
            "before": {
                "bid_strategy": "highest_volume",
                "ad_set_bids": '{"51":null,"52":null}',
            }
        },
    }
    http = httpx2.AsyncClient(transport=httpx2.MockTransport(graph.handle))
    ctx, audit = _tool_context(monkeypatch, http, proposed=_proposed(*edits), checks=checks)

    async with http:
        result = await tool_module.meta_ads_update_campaigns(ctx, changes=edits)

    MetaAdsUpdateCampaignsOutput.model_validate(result)
    assert graph.dry_runs == ["9", "6", "5"] and graph.posts == ["9", "6", "5"]
    assert graph.sent[0] == {"spend_cap": "50000"}
    assert graph.sent[2]["bid_strategy"] == "COST_CAP"
    assert json.loads(graph.sent[2]["adset_bid_amounts"]) == {"51": 1200, "52": 950}
    rows = result["results"][0]["data"]["campaigns"]
    assert [row["outcome"] for row in rows] == ["updated", "updated", "updated"]
    assert [(bid["adset_id"], bid["after"]) for bid in rows[2]["ad_set_bids"]] == [
        ("51", "12"),
        ("52", "9.5"),
    ]
    pending = audit.await_args_list[0].kwargs["operation_detail"].intent_groups[0].items
    assert pending[0].fields["requested"] == {"spend_limit": "50000"}
    assert pending[2].fields["requested"]["ad_set_bids"] == {"51": "1200", "52": "950"}


async def test_a_campaign_outside_the_selected_ad_accounts_is_refused(monkeypatch):
    graph = CampaignGraph([])
    edit = MetaAdsCampaignEdit(campaign=_reference("9", account_id="999"), name="Spring")
    http = httpx2.AsyncClient(transport=httpx2.MockTransport(graph.handle))
    ctx, audit = _tool_context(monkeypatch, http, proposed=_proposed(edit), checks={})

    async with http:
        with pytest.raises(ModelRetry, match="no longer in the active integration context"):
            await tool_module.meta_ads_update_campaigns(ctx, changes=[edit])

    assert graph.dry_runs == [] and graph.posts == [] and audit.await_count == 0


def test_the_card_can_change_a_bid_but_not_add_an_ad_set_bid():
    proposed = _proposed(_edit(bid_strategy="bid_cap", ad_set_bids=[_bid("51", "3")]))

    tool_module._require_proposed(
        proposed,
        MetaAdsUpdateCampaignsRequest(
            changes=[_edit(bid_strategy="bid_cap", ad_set_bids=[_bid("51", "4")])]
        ),
    )
    with pytest.raises(ModelRetry, match="added after approval"):
        tool_module._require_proposed(
            proposed,
            MetaAdsUpdateCampaignsRequest(
                changes=[
                    _edit(bid_strategy="bid_cap", ad_set_bids=[_bid("51", "4"), _bid("52", "4")])
                ]
            ),
        )


def _object(**fields) -> MetaAdsObject:
    defaults = {
        "id": "9",
        "name": "Campaign",
        "status": "ACTIVE",
        "effective_status": "ACTIVE",
        "objective": "OUTCOME_SALES",
        "optimization_goal": None,
        "bid_strategy": "LOWEST_COST_WITHOUT_CAP",
        "budget": {"kind": "daily", "amount": "100", "remaining": None},
        "bid_amount": None,
        "start_time": None,
        "end_time": None,
        "campaign_id": None,
        "adset_id": None,
    }
    return MetaAdsObject.model_validate({**defaults, **fields})


def _problems(edit, campaign=None, ad_sets=(), spent=None):
    return edit_problems(
        edit,
        campaign or _object(),
        list(ad_sets),
        currency="EUR",
        spent=spent,
        minimum_spend_limit="100",
    )


def test_a_cost_goal_without_a_bid_for_every_ad_set_is_refused():
    ad_sets = [_object(id="51", name="Prospecting"), _object(id="52", name="Retargeting")]
    edit = _edit(bid_strategy="cost_per_result_goal", ad_set_bids=[_bid("51", "12")])

    assert _problems(edit, ad_sets=ad_sets) == [
        "This bid strategy needs a bid on every ad set. Add one for Retargeting."
    ]


def test_a_spending_limit_at_or_below_lifetime_spend_is_refused():
    assert _problems(_edit(spend_limit="300"), spent="312.40") == [
        "This campaign has spent 312.40 EUR so far, so set a spending limit above that."
    ]


def test_a_campaign_in_legacy_advantage_shopping_is_refused():
    campaign = _object(smart_promotion_type="AUTOMATED_SHOPPING_ADS")

    problems = _problems(_edit(name="Renamed"), campaign=campaign)

    assert problems and "no longer allows changes" in problems[0]
