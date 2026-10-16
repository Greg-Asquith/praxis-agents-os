# apps/api/tests/integrations/meta_ads/test_update_ad_sets.py

"""Ad set setting edits: Meta's rules before approval, stale proposals, and read-back proof."""

import json
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock
from urllib.parse import parse_qsl
from uuid import uuid4
from zoneinfo import ZoneInfo

import httpx2
import pytest
from pydantic_ai import ModelRetry

from integrations.meta_ads.client import MetaAdsClient
from integrations.meta_ads.operations.edit_ad_set import ad_set_values, edit_problems
from integrations.meta_ads.operations.edit_impact import LEARNING_NOTE, lifetime_pace, pace_note
from integrations.meta_ads.operations.list_objects import read_objects_by_id
from integrations.meta_ads.operations.update_fields import FieldChange, update_fields
from integrations.meta_ads.references import MetaAdsAdSetReference
from integrations.meta_ads.tools import update_ad_sets as tool_module
from integrations.meta_ads.tools.schemas.ad_set_edits import (
    MetaAdsAdSetEdit,
    MetaAdsUpdateAdSetsOutput,
)
from integrations.meta_ads.tools.schemas.objects import MetaAdsObject
from services.integrations.context.domain import ResolvedActiveContext
from tests.integrations.meta_ads.support import FakeGraph, context_entry, obj, static_token

ZONE = ZoneInfo("Europe/Paris")
TODAY = datetime.now(UTC).astimezone(ZONE).date()
END = TODAY + timedelta(days=40)
LATER = TODAY + timedelta(days=60)


class EditGraph(FakeGraph):
    """Applies every posted ad set setting, the way Meta stores it."""

    def handle_post(self, request, object_id):
        response = super().handle_post(request, object_id)
        form = dict(parse_qsl(request.content.decode()))
        if "execution_options" not in form and self.post.get(object_id, "apply") == "apply":
            item = self.objects[object_id]
            for key, value in form.items():
                item[key] = json.loads(value) if key == "bid_constraints" else value
            if form.get("end_time") == "0":
                del item["end_time"]
        return response


def _end_time(day: date) -> str:
    return datetime.combine(day, datetime.min.time(), tzinfo=ZONE).replace(hour=12).isoformat()


def _ad_set(adset_id="8", **fields):
    defaults = {
        "campaign_id": "9",
        "status": "ACTIVE",
        "daily_budget": "5000",
        "bid_strategy": "COST_CAP",
        "bid_amount": "1500",
        "end_time": _end_time(END),
        "targeting": {"geo_locations": {"countries": ["GB"]}},
    }
    return obj(adset_id, "adset", **{**defaults, **fields})


def _reference(adset_id="8", account_id="123") -> MetaAdsAdSetReference:
    return MetaAdsAdSetReference(
        account_id=account_id, campaign_id="9", adset_id=adset_id, label=f"Ad set {adset_id}"
    )


def _edit(adset_id="8", **settings) -> MetaAdsAdSetEdit:
    return MetaAdsAdSetEdit(ad_set=_reference(adset_id), **settings)


def _before(graph: EditGraph, *ids: str) -> dict:
    """What the approval card showed: each ad set's settings as they were when proposed."""
    checks = {}
    for adset_id in ids:
        raw = graph.objects[adset_id]
        checks[adset_id] = {
            "before": {
                "end_date": _end_time(END)[:10] if "end_time" in raw else None,
                "bid_amount": format(int(raw["bid_amount"]) / 100, "g")
                if raw.get("bid_amount")
                else None,
                "max_daily_spend": None,
            }
        }
    return checks


def _tool_context(monkeypatch, http, *, proposed, checks):
    audit = AsyncMock(return_value=uuid4())
    monkeypatch.setattr(
        "services.integrations.operations.record_integration_operation_audit_event", audit
    )
    checkpoint = AsyncMock()
    monkeypatch.setattr(
        "integrations.meta_ads.operations.update_fields.checkpoint_integration_operation",
        checkpoint,
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
        tool_name="meta_ads_update_ad_sets",
        tool_call_id="call-meta-ad-sets",
    )
    return ctx, audit, checkpoint


def _proposed(*edits: MetaAdsAdSetEdit) -> dict:
    return {"changes": [edit.model_dump(mode="json", exclude_none=True) for edit in edits]}


async def test_one_approval_extends_dates_lowers_a_cost_goal_and_caps_daily_spend(monkeypatch):
    graph = EditGraph(
        [
            obj("9", "campaign", status="ACTIVE"),
            obj("6", "campaign", status="ACTIVE", daily_budget="10000"),
            _ad_set("8"),
            _ad_set(
                "7",
                campaign_id="6",
                daily_budget=None,
                bid_strategy="LOWEST_COST_WITHOUT_CAP",
                bid_amount=None,
                campaign={"daily_budget": "10000"},
            ),
        ]
    )
    edits = [
        _edit("8", end_date=LATER.isoformat(), bid_amount="12"),
        _edit("7", end_date=LATER.isoformat(), max_daily_spend="30"),
    ]
    http = httpx2.AsyncClient(transport=httpx2.MockTransport(graph.handle))
    ctx, audit, checkpoint = _tool_context(
        monkeypatch, http, proposed=_proposed(*edits), checks=_before(graph, "8", "7")
    )

    async with http:
        result = await tool_module.meta_ads_update_ad_sets(ctx, changes=edits)

    MetaAdsUpdateAdSetsOutput.model_validate(result)
    assert graph.dry_runs == ["8", "7"] and graph.posts == ["8", "7"]
    end_time = f"{LATER.isoformat()}T23:59:59"
    assert graph.sent[0]["bid_amount"] == "1200"
    assert graph.sent[0]["end_time"].startswith(end_time)
    assert graph.sent[1]["daily_spend_cap"] == "3000"
    rows = result["results"][0]["data"]["ad_sets"]
    assert [row["outcome"] for row in rows] == ["updated", "updated"]
    assert rows[0]["changes"][1] == {
        "setting": "bid_amount",
        "before": "15",
        "requested": "12",
        "after": "12",
    }
    # Each ad set is marked before its change is sent, so recovery knows what may have changed.
    assert [call.args[0].intent_index for call in checkpoint.await_args_list] == [0, 1]
    pending = audit.await_args_list[0].kwargs["operation_detail"].intent_groups[0].items[0]
    assert pending.fields["requested"] == {"end_date": LATER.isoformat(), "bid_amount": "1200"}


async def test_a_dry_run_rejection_sends_nothing_and_keeps_metas_reason(monkeypatch):
    graph = EditGraph(
        [obj("9", "campaign", status="ACTIVE"), _ad_set("8")], post={"8": "reject_dry_run"}
    )
    edit = _edit("8", end_date=LATER.isoformat())
    http = httpx2.AsyncClient(transport=httpx2.MockTransport(graph.handle))
    ctx, _audit, _checkpoint = _tool_context(
        monkeypatch, http, proposed=_proposed(edit), checks=_before(graph, "8")
    )

    async with http:
        result = await tool_module.meta_ads_update_ad_sets(ctx, changes=[edit])

    entry = result["results"][0]
    assert graph.dry_runs == ["8"] and graph.posts == []
    assert entry["status"] == "error"
    assert "The budget is too low." in entry["error_message"]


async def test_an_ad_set_that_changed_after_approval_is_not_sent(monkeypatch):
    graph = EditGraph([obj("9", "campaign", status="ACTIVE"), _ad_set("8"), _ad_set("7")])
    edits = [_edit("8", end_date=LATER.isoformat()), _edit("7", end_date=LATER.isoformat())]
    shown = _before(graph, "8", "7")
    # Someone moved ad set 8's end date in Ads Manager after the card was shown.
    graph.objects["8"]["end_time"] = _end_time(END + timedelta(days=5))
    http = httpx2.AsyncClient(transport=httpx2.MockTransport(graph.handle))
    ctx, _audit, _checkpoint = _tool_context(
        monkeypatch, http, proposed=_proposed(*edits), checks=shown
    )

    async with http:
        result = await tool_module.meta_ads_update_ad_sets(ctx, changes=edits)

    stale, kept = result["results"][0]["data"]["ad_sets"]
    assert graph.posts == ["7"]
    assert (stale["outcome"], stale["error_code"]) == ("failed", "CHANGED_SINCE_APPROVAL")
    assert kept["outcome"] == "updated"


async def test_an_ad_set_outside_the_selected_ad_accounts_is_refused(monkeypatch):
    graph = EditGraph([])
    edit = MetaAdsAdSetEdit(ad_set=_reference("8", account_id="999"), name="Spring")
    http = httpx2.AsyncClient(transport=httpx2.MockTransport(graph.handle))
    ctx, audit, _checkpoint = _tool_context(monkeypatch, http, proposed=_proposed(edit), checks={})

    async with http:
        with pytest.raises(ModelRetry, match="no longer in the active integration context"):
            await tool_module.meta_ads_update_ad_sets(ctx, changes=[edit])

    assert graph.dry_runs == [] and graph.posts == [] and audit.await_count == 0


async def test_an_ambiguous_send_is_not_retried_and_a_disagreeing_read_back_fails(monkeypatch):
    sleep = AsyncMock()
    monkeypatch.setattr("services.integrations.http.asyncio.sleep", sleep)
    monkeypatch.setattr(
        "integrations.meta_ads.operations.update_fields.checkpoint_integration_operation",
        AsyncMock(),
    )
    graph = EditGraph(
        [_ad_set("8"), _ad_set("7")], post={"8": "timeout", "7": "accept_without_change"}
    )
    async with httpx2.AsyncClient(transport=httpx2.MockTransport(graph.handle)) as http:
        client = MetaAdsClient(static_token, client=http)
        found = await read_objects_by_id(
            client, account_id="123", object_type="adset", object_ids=["8", "7"], currency="EUR"
        )
        changes = [
            FieldChange(
                object_type="adset",
                before=found[adset_id],
                before_values={"bid_amount": "15"},
                requested={"bid_amount": "12"},
                body={"bid_amount": "1200"},
            )
            for adset_id in ("8", "7")
        ]
        ledger = await update_fields(
            client,
            account_id="123",
            currency="EUR",
            changes=changes,
            values=lambda item: ad_set_values(item, ZONE),
            action="update_ad_sets",
            group_key="adsets:update-settings",
            operation="update_ad_sets",
        )

    assert graph.posts == ["8", "7"]
    sleep.assert_not_awaited()
    lost, unchanged = ledger.parents
    assert lost.outcome == "unverified"
    assert unchanged.outcome == "failed"
    # The value Meta still shows is kept, so the result shows what is really set.
    assert dict(unchanged.effects[0].fields)["after.bid_amount"] == "15"


def _object(**fields) -> MetaAdsObject:
    defaults = {
        "id": "8",
        "name": "Ad set",
        "status": "ACTIVE",
        "effective_status": "ACTIVE",
        "objective": "OUTCOME_SALES",
        "optimization_goal": "OFFSITE_CONVERSIONS",
        "bid_strategy": "LOWEST_COST_WITHOUT_CAP",
        "budget": {"kind": "daily", "amount": "50", "remaining": None},
        "bid_amount": None,
        "start_time": None,
        "end_time": None,
        "campaign_id": "9",
        "adset_id": None,
    }
    return MetaAdsObject.model_validate({**defaults, **fields})


def _problems(edit: MetaAdsAdSetEdit, ad_set: MetaAdsObject, campaign: MetaAdsObject):
    return edit_problems(edit, ad_set, campaign, currency="EUR", zone=ZONE, today=TODAY)


def test_a_bid_strategy_is_refused_when_the_campaign_holds_the_budget():
    campaign = _object(id="9", budget={"kind": "daily", "amount": "100", "remaining": None})

    problems = _problems(_edit(bid_strategy="bid_cap", bid_amount="2"), _object(), campaign)

    assert problems == ["The campaign sets the bid strategy for its ad sets, so change it there."]


def test_a_daily_spend_cap_under_a_campaign_lifetime_budget_is_refused():
    under_lifetime = {"kind": "campaign", "amount": "900", "remaining": None, "period": "lifetime"}

    problems = _problems(
        _edit(max_daily_spend="30"), _object(budget=under_lifetime), _object(id="9")
    )

    assert problems == ["Daily spend limits need a campaign daily budget."]


def test_running_a_lifetime_budget_continuously_is_refused():
    lifetime = _object(
        budget={"kind": "lifetime", "amount": "900", "remaining": "500"},
        end_time=_end_time(END),
    )

    problems = _problems(_edit(end_date="none"), lifetime, _object(id="9"))

    assert problems == ["A lifetime budget needs an end date, so keep end_date."]


def test_an_ad_set_in_a_legacy_advantage_shopping_campaign_is_refused():
    campaign = _object(id="9", smart_promotion_type="AUTOMATED_SHOPPING_ADS")

    problems = _problems(_edit(name="Renamed"), _object(), campaign)

    assert problems and "copy it in Ads Manager" in problems[0]


async def test_the_card_notes_learning_and_the_ad_bids_a_new_bid_replaces():
    graph = EditGraph(
        [
            obj("9", "campaign", status="ACTIVE"),
            _ad_set("8", learning_stage_info={"status": "LEARNING"}),
            obj("81", "ad", status="ACTIVE", campaign_id="9", adset_id="8", bid_amount="900"),
            obj("82", "ad", status="ACTIVE", campaign_id="9", adset_id="8"),
        ]
    )
    entry = replace(context_entry("123"), write_allowed=True)
    async with httpx2.AsyncClient(transport=httpx2.MockTransport(graph.handle)) as http:
        (review,) = await tool_module._review_account(
            MetaAdsClient(static_token, client=http),
            entry,
            [_edit("8", bid_amount="12")],
            now=datetime.now(UTC),
            with_notes=True,
        )

    assert review.problems == []
    assert review.warnings == [LEARNING_NOTE]
    assert review.notes == ["This bid replaces the bids set on 1 ad in this ad set."]
    assert graph.posts == []


def test_a_shorter_lifetime_schedule_spreads_the_rest_of_the_budget_over_fewer_days():
    ad_set = _object(
        budget={"kind": "lifetime", "amount": "2000", "remaining": "1680"},
        end_time=_end_time(TODAY + timedelta(days=41)),
    )

    pace = lifetime_pace(
        ad_set, start=None, end=TODAY + timedelta(days=29), today=TODAY, currency="EUR"
    )

    assert pace is not None
    assert pace_note(pace, "EUR") == (
        "The lifetime budget now has 12 fewer days, so it spends about 56 EUR a day instead "
        "of 40 EUR."
    )
