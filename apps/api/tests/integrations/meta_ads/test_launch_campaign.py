# apps/api/tests/integrations/meta_ads/test_launch_campaign.py

"""Launching a Meta campaign: build order, where a build stops, and when it turns on."""

import json
import time
from urllib.parse import parse_qsl

import httpx2

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
from integrations.meta_ads.tools.schemas.launch import MetaAdsLaunchCampaignRequest
from integrations.meta_ads.tools.utils.mutation_evidence import (
    audit_status,
    meta_ads_account_target,
    terminal_operation_detail,
)
from services.audit_events import AuditStatus, PendingIntegrationOperationDetail
from tests.integrations.meta_ads.support import (
    GRAPH_EDGES,
    FakeGraph,
    context_entry,
    obj,
    static_token,
)

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


class LaunchGraph(FakeGraph):
    """Dry-runs and creates campaigns, ad sets, and ads by name, and applies status changes."""

    def __init__(self, behaviour=None, turn_on=None):
        super().__init__([], account={"currency": "GBP"})
        self.behaviour = behaviour or {}
        self.turn_on = turn_on or {}
        self.creates: list[tuple[str, dict[str, str]]] = []
        self.next_id = 900

    def handle(self, request: httpx2.Request) -> httpx2.Response:
        path = request.url.path.split("/")[2:]
        if request.method == "POST" and path[0] == "act_123":
            return self.create(request, path[1])
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
