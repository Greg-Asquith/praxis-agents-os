# apps/api/tests/integrations/meta_ads/test_launch_campaign.py

"""Launching a Meta campaign: build order, where a build stops, and when it turns on."""

import json
import time
from dataclasses import replace
from unittest.mock import AsyncMock
from urllib.parse import parse_qsl
from uuid import uuid4

import httpx2
import pytest
from pydantic_ai import ModelRetry

from integrations.meta_ads import throttle
from integrations.meta_ads.client import MetaAdsClient
from integrations.meta_ads.operations.create_campaign import plan_campaign
from integrations.meta_ads.operations.creatives import CreativeImage
from integrations.meta_ads.operations.launch_campaign import (
    AdSetTerms,
    launch_campaign,
    launch_intent_groups,
    launch_problems,
    plan_launch,
)
from integrations.meta_ads.tools import launch_campaign as tool_module
from integrations.meta_ads.tools.launch_campaign import meta_ads_launch_campaign
from integrations.meta_ads.tools.schemas.launch import (
    MetaAdsLaunchCampaignOutput,
    MetaAdsLaunchCampaignRequest,
)
from integrations.meta_ads.tools.utils import ad_preparation as preparation_module
from integrations.meta_ads.tools.utils.mutation_evidence import (
    audit_status,
    meta_ads_account_target,
    terminal_operation_detail,
)
from services.audit_events import AuditStatus, PendingIntegrationOperationDetail
from services.integrations.files import FileReference
from tests.integrations.meta_ads.support import (
    GRAPH_EDGES,
    FakeGraph,
    context_entry,
    obj,
    runtime_ctx,
    static_token,
    write_tool_context,
)
from tests.integrations.meta_ads.test_create_ads import file_source

PAGE = {"account_id": "123", "page_id": "11", "label": "Acme"}
IMAGE = {
    "entity_kind": "meta_ads_media",
    "account_id": "123",
    "media_type": "image",
    "image_hash": "abc",
    "label": "hero.jpg",
}
THROTTLE_HEADERS = {
    "x-business-use-case-usage": json.dumps(
        {
            "123": [
                {"type": "ads_management", "call_count": 100, "estimated_time_to_regain_access": 5}
            ]
        }
    )
}


def ad_set(key: str, name: str, **overrides) -> dict:
    return {
        "key": key,
        "name": name,
        "goal": "website_conversions",
        "targeting": {"locations": [{"kind": "country", "key": "GB"}]},
        "pixel": {"account_id": "123", "pixel_id": "77", "label": "Shop Pixel"},
        "conversion_event": "PURCHASE",
        **overrides,
    }


def ad(name: str, *keys: str, **overrides) -> dict:
    return {
        "name": name,
        "ad_set_keys": list(keys),
        "format": "image",
        "primary_text": "Spring sale on now",
        "headline": "20% off",
        "media": IMAGE,
        **overrides,
    }


def launch(**overrides) -> MetaAdsLaunchCampaignRequest:
    values = {
        "campaign": {
            "name": "Spring Sale",
            "objective": "sales",
            "budget": {"mode": "campaign_daily", "amount": "60"},
        },
        "ad_sets": [ad_set("prospecting", "Prospecting"), ad_set("retargeting", "Retargeting")],
        "ads": [ad("Hero", "prospecting"), ad("Offer", "retargeting")],
        "page": PAGE,
        "link": "https://shop.example.com/spring",
        **overrides,
    }
    return MetaAdsLaunchCampaignRequest.model_validate(values)


def plan(request: MetaAdsLaunchCampaignRequest):
    return plan_launch(
        request,
        campaign=plan_campaign(request.campaign, currency="GBP", start_time=None, end_time=None),
        currency="GBP",
        terms={item.key: AdSetTerms(None, None, "not_needed") for item in request.ad_sets},
        sources=[],
        media={("image", "abc"): CreativeImage("abc")},
    )


ASSETS = {
    "promote_pages": [{"id": "11", "name": "Acme"}],
    "adspixels": [{"id": "77", "name": "Shop Pixel"}],
    "adimages": [{"hash": "abc", "name": "hero.jpg", "status": "ACTIVE"}],
    "minimum_budgets": [],
}


class LaunchGraph(FakeGraph):
    """Serves the account's assets, dry-runs and creates objects by name, and turns them on."""

    def __init__(self, behaviour=None, turn_on=None):
        super().__init__(
            [],
            account={"currency": "GBP", "timezone_name": "Europe/London", "min_daily_budget": 100},
        )
        self.behaviour = behaviour or {}
        self.turn_on = turn_on or {}
        self.creates: list[tuple[str, dict[str, str]]] = []
        self.next_id = 900

    def handle(self, request: httpx2.Request) -> httpx2.Response:
        path = request.url.path.split("/")[2:]
        if request.method == "POST" and path[0] == "act_123":
            return self.create(request, path[1])
        if len(path) == 2 and path[1] in ASSETS:
            return httpx2.Response(200, json={"data": ASSETS[path[1]]}, request=request)
        return super().handle(request)

    def create(self, request: httpx2.Request, edge: str) -> httpx2.Response:
        form = dict(parse_qsl(request.content.decode()))
        behaviour = self.behaviour.get(form["name"], "apply")
        if "execution_options" in form:
            if behaviour == "reject_dry_run":
                error = {"code": 100, "error_user_msg": "The link is broken.", "fbtrace_id": "t"}
                return httpx2.Response(400, json={"error": error}, request=request)
            return httpx2.Response(200, json={"success": True}, request=request)
        self.creates.append((edge, form))
        if behaviour == "throttle":
            error = {"code": 613, "error_subcode": 1487742, "fbtrace_id": "t"}
            return httpx2.Response(
                400, json={"error": error}, headers=THROTTLE_HEADERS, request=request
            )
        for _ in range(2 if behaviour == "lose_reply_twice" else 1):
            object_id = self.add(edge, form)
        if behaviour == "lose_reply_twice":
            raise httpx2.ReadTimeout("lost", request=request)
        return httpx2.Response(200, json={"id": object_id}, request=request)

    def add(self, edge: str, form: dict[str, str]) -> str:
        object_id = str(self.next_id)
        self.next_id += 1
        row = obj(
            object_id,
            GRAPH_EDGES[edge],
            name=form["name"],
            status=form["status"],
            created_time="2099-01-01T00:00:00+0000",
        )
        if edge == "adsets":
            row["campaign_id"] = form["campaign_id"]
        if edge == "ads":
            creative = json.loads(form["creative"])
            for feature in self.turn_on.get(form["name"], ()):
                features = creative["degrees_of_freedom_spec"]["creative_features_spec"]
                features[feature] = {"enroll_status": "OPT_IN"}
            row.update(
                adset_id=form["adset_id"],
                campaign_id=self.objects[form["adset_id"]]["campaign_id"],
                effective_status="PENDING_REVIEW",
                creative={"id": f"5{object_id}", **creative},
            )
        self.objects[object_id] = row
        return object_id

    def created(self, edge: str) -> list[dict[str, str]]:
        return [form for sent_edge, form in self.creates if sent_edge == edge]


async def run_launch(graph: LaunchGraph, request: MetaAdsLaunchCampaignRequest, *, deadline=None):
    launch_plan = plan(request)
    async with httpx2.AsyncClient(transport=httpx2.MockTransport(graph.handle)) as http:
        run = await launch_campaign(
            MetaAdsClient(static_token, client=http),
            account_id="123",
            currency="GBP",
            scope_label="Account 123",
            plan=launch_plan,
            deadline=time.monotonic() + 60 if deadline is None else deadline,
        )
    pending = PendingIntegrationOperationDetail(
        target=meta_ads_account_target(context_entry("123")),
        intent_groups=launch_intent_groups(launch_plan),
    )
    # The ledger must account for every intent recorded before the build.
    detail = terminal_operation_detail(pending, run.ledger(), identity_key="key")
    return run, audit_status(detail)


async def test_a_full_launch_builds_paused_then_turns_on_ad_sets_and_the_campaign_last():
    graph = LaunchGraph()

    run, status = await run_launch(graph, launch(go_live=True))

    assert [form["status"] for form in graph.created("campaigns")] == ["PAUSED"]
    assert [form["status"] for form in graph.created("adsets")] == ["PAUSED", "PAUSED"]
    assert [form["status"] for form in graph.created("ads")] == ["ACTIVE", "ACTIVE"]
    campaign_id = graph.created("adsets")[0]["campaign_id"]
    # Status changes go to the ad sets first and the campaign last, so nothing spends early.
    assert graph.posts[-1] == campaign_id and len(graph.posts) == 3
    assert (run.state, status) == ("live", AuditStatus.SUCCESS)


async def test_without_go_live_everything_is_built_paused_and_nothing_is_turned_on():
    graph = LaunchGraph()

    run, status = await run_launch(graph, launch())

    assert [form["status"] for form in graph.created("ads")] == ["PAUSED", "PAUSED"]
    assert graph.posts == []
    assert (run.state, status) == ("paused", AuditStatus.SUCCESS)


async def test_a_rejected_ad_set_skips_its_ads_while_the_rest_is_built_and_nothing_turns_on():
    graph = LaunchGraph({"Prospecting": "reject_dry_run"})

    run, status = await run_launch(graph, launch(go_live=True))

    assert [form["name"] for form in graph.created("adsets")] == ["Retargeting"]
    assert [form["name"] for form in graph.created("ads")] == ["Offer"]
    assert run.ads[0].skip_code == "AD_SET_NOT_CREATED"
    assert graph.posts == []
    assert (run.state, status) == ("partial", AuditStatus.PARTIAL)


async def test_a_rejected_ad_fails_alone_and_its_siblings_are_still_created():
    graph = LaunchGraph({"Hero": "reject_dry_run"})
    request = launch(
        ads=[ad("Hero", "prospecting"), ad("Extra", "prospecting"), ad("Offer", "retargeting")]
    )

    run, status = await run_launch(graph, request)

    assert [form["name"] for form in graph.created("ads")] == ["Extra", "Offer"]
    assert "The link is broken." in (run.ads[0].skip_message or "")
    assert (run.state, status) == ("partial", AuditStatus.PARTIAL)


async def test_an_unsettled_ad_set_create_stops_the_build_as_unverified():
    graph = LaunchGraph({"Prospecting": "lose_reply_twice"})

    run, status = await run_launch(graph, launch(go_live=True))

    assert [form["name"] for form in graph.created("adsets")] == ["Prospecting"]
    assert graph.created("ads") == [] and graph.posts == []
    assert (run.stopped, run.state, status) == ("unverified", "stopped", AuditStatus.UNVERIFIED)


async def test_a_throttled_create_stops_the_build_with_metas_wait_time():
    graph = LaunchGraph({"Prospecting": "throttle"})

    run, status = await run_launch(graph, launch(go_live=True))

    assert [form["name"] for form in graph.created("adsets")] == ["Prospecting"]
    assert run.stopped == "throttled"
    assert "Try again in 5 minutes" in (run.stop_message or "")
    assert (run.state, status) == ("partial", AuditStatus.PARTIAL)


async def test_an_automatic_change_meta_turned_on_blocks_going_live():
    graph = LaunchGraph(turn_on={"Hero": ["inline_comment"]})

    run, status = await run_launch(graph, launch(go_live=True))

    assert len(graph.created("ads")) == 2
    assert graph.posts == []
    assert "automatic changes" in (run.held or "")
    assert (run.state, status) == ("partial", AuditStatus.PARTIAL)


async def test_no_step_starts_after_the_deadline():
    graph = LaunchGraph()

    run, _status = await run_launch(graph, launch(go_live=True), deadline=time.monotonic())

    assert len(graph.created("campaigns")) == 1
    assert graph.created("adsets") == []
    # What was built is read back, so the step tools can finish it.
    assert (run.stopped, run.campaign.created.id) == ("deadline", "900")


def test_ad_sets_are_checked_against_the_campaign_the_launch_creates():
    # The campaign holds the budget, so an ad set budget is refused before anything exists.
    request = launch(
        ad_sets=[
            ad_set("prospecting", "Prospecting", budget={"kind": "daily", "amount": "20"}),
            ad_set("retargeting", "Retargeting"),
        ]
    )

    assert launch_problems(request) == [
        "Prospecting: This campaign holds the budget, so leave the ad set's budget out."
    ]


async def run_tool(monkeypatch, graph: LaunchGraph, request: MetaAdsLaunchCampaignRequest, **kw):
    http = httpx2.AsyncClient(transport=httpx2.MockTransport(graph.handle))
    ctx, audit = write_tool_context(
        monkeypatch,
        http,
        tool_name="meta_ads_launch_campaign",
        proposed=request.model_dump(mode="json"),
        reviewed=kw.get("reviewed"),
        tool_modules=(tool_module, preparation_module),
    )
    async with http:
        result = await meta_ads_launch_campaign(ctx, **dict(request))
    MetaAdsLaunchCampaignOutput.model_validate(result)
    return result["results"][0], audit


async def test_one_approval_checks_then_builds_and_turns_on_the_whole_campaign(monkeypatch):
    graph = LaunchGraph()

    entry, audit = await run_tool(monkeypatch, graph, launch(go_live=True))

    data = entry["data"]
    # The campaign is dry-run at preparation, before the pending event and any create.
    assert graph.creates[0][0] == "campaigns"
    assert audit.await_args_list[0].kwargs["status"] == AuditStatus.PENDING
    assert (data["state"], data["campaign_turned_on"]) == ("live", "turned_on")
    assert [row["turned_on"] for row in data["ad_sets"]] == ["turned_on", "turned_on"]
    # Created references come back, so the step tools can extend the campaign.
    assert data["campaign"]["campaign"]["campaign_id"] == data["ad_sets"][0]["campaign_id"]
    assert {row["ad_set_key"]: row["adset_id"] for row in data["ads"]} == {
        row["key"]: row["adset_id"] for row in data["ad_sets"]
    }
    assert audit.await_args_list[-1].kwargs["status"] == AuditStatus.SUCCESS


async def test_a_preparation_rejection_creates_nothing(monkeypatch):
    graph = LaunchGraph({"Spring Sale": "reject_dry_run"})

    entry, audit = await run_tool(monkeypatch, graph, launch(go_live=True))

    assert entry["status"] == "error"
    assert "The link is broken." in entry["error_message"]
    assert graph.creates == []
    assert all(call.kwargs["status"] != AuditStatus.PENDING for call in audit.await_args_list)


async def test_usage_at_three_quarters_of_the_hourly_allowance_fails_fast(monkeypatch):
    graph = LaunchGraph()
    usage = {"type": "ads_management", "call_count": 80, "estimated_time_to_regain_access": 12}
    throttle.record_usage("123", {"x-business-use-case-usage": json.dumps({"123": [usage]})})

    entry, _audit = await run_tool(monkeypatch, graph, launch(go_live=True))

    assert entry["status"] == "error"
    assert "12 minutes" in entry["error_message"]
    assert graph.creates == []


async def test_a_file_changed_after_approval_fails_in_preparation(monkeypatch):
    graph = LaunchGraph()
    source = file_source()
    monkeypatch.setattr(preparation_module, "resolve_media_source", AsyncMock(return_value=source))
    image = FileReference(entity_id=source.file.id, label="spring.png").model_dump(mode="json")
    request = launch(ads=[ad("Hero", "prospecting", media=image), ad("Offer", "retargeting")])
    stale = {**source.approval_details(), "revision_id": str(uuid4())}

    entry, _audit = await run_tool(monkeypatch, graph, request, reviewed={"_files": [stale]})

    assert entry["error_code"] == "source_changed"
    assert graph.creates == []


async def test_an_asset_from_another_ad_account_cant_be_named():
    other_pixel = {"account_id": "456", "pixel_id": "88", "label": "Their Pixel"}
    values = launch().model_dump(mode="json")
    values["ad_sets"][0]["pixel"] = other_pixel
    entry = replace(context_entry("123"), write_allowed=True)

    with pytest.raises(ModelRetry, match="one ad account"):
        await tool_module._validate_args(runtime_ctx(entry), **values)


async def test_evidence_for_a_launch_at_the_maximum_size_stays_within_the_bound():
    regions = [
        {"kind": "region", "key": f"{index:032d}", "country_code": "GB"} for index in range(200)
    ]
    cards = [
        {"media": {**IMAGE, "image_hash": f"h{index}"}, "headline": "20% off"}
        for index in range(10)
    ]
    keys = [f"ad_set_{index}" for index in range(10)]
    request = launch(
        ad_sets=[ad_set(key, key, targeting={"locations": regions}) for key in keys],
        ads=[
            ad(
                f"Ad {index}",
                keys[index % 10],
                format="carousel",
                media=None,
                headline=None,
                cards=cards,
            )
            for index in range(50)
        ],
        go_live=True,
    )
    launch_plan = plan_launch(
        request,
        campaign=plan_campaign(request.campaign, currency="GBP", start_time=None, end_time=None),
        currency="GBP",
        terms={key: AdSetTerms(None, None, "not_needed") for key in keys},
        sources=[],
        media={("image", f"h{index}"): CreativeImage(f"h{index}") for index in range(10)},
    )
    graph = LaunchGraph()

    async with httpx2.AsyncClient(transport=httpx2.MockTransport(graph.handle)) as http:
        run = await launch_campaign(
            MetaAdsClient(static_token, client=http),
            account_id="123",
            currency="GBP",
            scope_label="Account 123",
            plan=launch_plan,
            deadline=time.monotonic() + 60,
        )
    pending = PendingIntegrationOperationDetail(
        target=meta_ads_account_target(context_entry("123")),
        intent_groups=launch_intent_groups(launch_plan),
    )

    # Both details validate their own size and item limits when built.
    terminal = terminal_operation_detail(pending, run.ledger(), identity_key="key")
    assert (run.state, len(graph.created("ads"))) == ("live", 50)
    assert len(terminal.model_dump_json()) < 1_000_000
