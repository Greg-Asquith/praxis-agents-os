# apps/api/tests/integrations/meta_ads/test_create_ad_set.py

"""Creating Meta ad sets: campaign rules before approval, a dry run, one send, and proof after."""

import json
from dataclasses import replace
from urllib.parse import parse_qsl

import httpx2
import pytest
from pydantic_ai import ModelRetry

from integrations.meta_ads.operations.create_ad_set import campaign_problems, plan_ad_set
from integrations.meta_ads.references import MetaAdsCampaignReference
from integrations.meta_ads.tools import create_ad_set as tool_module
from integrations.meta_ads.tools.create_ad_set import meta_ads_create_ad_set
from integrations.meta_ads.tools.schemas.ad_sets import (
    MetaAdsCreateAdSetOutput,
    MetaAdsCreateAdSetRequest,
)
from tests.integrations.meta_ads.support import (
    FakeGraph,
    context_entry,
    obj,
    runtime_ctx,
    write_tool_context,
)

INTEREST = "Marathon running"
ASSETS = {
    "promote_pages": [{"id": "11", "name": "Shop Page"}],
    "adspixels": [{"id": "77", "name": "Shop Pixel"}],
    "advertisable_applications": [
        {
            "id": "55",
            "name": "Shop App",
            "object_store_urls": {"google_play": "https://play.google.com/store/apps/details?id=x"},
        }
    ],
    "customaudiences": [],
    "customconversions": [{"id": "300", "name": "Big basket", "pixel": {"id": "99"}}],
}


def campaign(**fields) -> dict:
    return obj("9", "campaign", objective="OUTCOME_SALES", special_ad_categories=[], **fields)


def args(**overrides) -> dict:
    values = {
        "campaign": {
            "account_id": "123",
            "campaign_id": "9",
            "label": "Spring",
            "objective": "OUTCOME_SALES",
        },
        "name": "UK runners",
        "goal": "website_conversions",
        "targeting": {
            "locations": [{"kind": "country", "key": "GB"}],
            "detailed": [[{"kind": "interest", "key": "600", "name": INTEREST}]],
        },
        "pixel": {"account_id": "123", "pixel_id": "77", "label": "Shop Pixel"},
        "conversion_event": "PURCHASE",
        "budget": {"kind": "daily", "amount": "40"},
    }
    return {**values, **overrides}


class AdSetGraph(FakeGraph):
    """Serves account assets and minimums, dry-runs ad sets, and creates them under the account."""

    def __init__(self, objects, *, account=None, behaviour="apply"):
        super().__init__(
            objects,
            account={"currency": "GBP", "timezone_name": "Europe/London", **(account or {})},
        )
        self.behaviour = behaviour
        self.creates: list[dict[str, str]] = []

    def handle(self, request: httpx2.Request) -> httpx2.Response:
        path = request.url.path.split("/")[2:]
        if request.method == "POST":
            return self.post_ad_set(request)
        if len(path) == 2 and path[1] in ASSETS:
            return httpx2.Response(200, json={"data": ASSETS[path[1]]}, request=request)
        if len(path) == 2 and path[1] == "minimum_budgets":
            row = {"currency": "GBP", "min_daily_budget_low_freq": 500}
            return httpx2.Response(200, json={"data": [row]}, request=request)
        return super().handle(request)

    def post_ad_set(self, request: httpx2.Request) -> httpx2.Response:
        form = dict(parse_qsl(request.content.decode()))
        if "execution_options" in form:
            self.dry_runs.append(form["name"])
            return httpx2.Response(200, json={"success": True}, request=request)
        self.creates.append(form)
        adset_id = str(800 + len(self.creates))
        self.objects[adset_id] = obj(
            adset_id,
            "adset",
            campaign_id=form["campaign_id"],
            name=form["name"],
            optimization_goal=form["optimization_goal"],
            destination_type=form.get("destination_type"),
            created_time="2099-01-01T00:00:00+0000",
            campaign={"objective": "OUTCOME_SALES"},
        )
        if self.behaviour == "lose_reply":
            raise httpx2.ReadTimeout("lost", request=request)
        return httpx2.Response(200, json={"id": adset_id}, request=request)


async def run_tool(monkeypatch, graph: AdSetGraph, values: dict, proposed: dict | None = None):
    http = httpx2.AsyncClient(transport=httpx2.MockTransport(graph.handle))
    ctx, audit = write_tool_context(
        monkeypatch, http, tool_name="meta_ads_create_ad_set", proposed=proposed or values
    )
    request = MetaAdsCreateAdSetRequest.model_validate(values)
    async with http:
        result = await meta_ads_create_ad_set(ctx, **{key: getattr(request, key) for key in values})
    MetaAdsCreateAdSetOutput.model_validate(result)
    return result["results"][0], audit


async def test_an_ad_set_is_dry_run_created_paused_once_and_read_back(monkeypatch):
    graph = AdSetGraph([campaign()])

    entry, audit = await run_tool(monkeypatch, graph, args())

    (sent,) = graph.creates
    assert graph.dry_runs == ["UK runners"]
    assert (sent["status"], sent["daily_budget"], sent["billing_event"]) == (
        "PAUSED",
        "4000",
        "IMPRESSIONS",
    )
    assert json.loads(sent["promoted_object"]) == {
        "pixel_id": "77",
        "custom_event_type": "PURCHASE",
    }
    row = entry["data"]["ad_set"]
    assert (row["outcome"], row["verified"], row["eu_transparency"]) == (
        "created",
        True,
        "not_needed",
    )
    # The read-back reference is what meta_ads_create_ads takes.
    assert (row["ad_set"]["adset_id"], row["ad_set"]["goal"]) == ("801", "website_conversions")
    pending = audit.await_args_list[0].kwargs["operation_detail"]
    fields = pending.intent_groups[0].items[0].fields
    assert (fields["daily_budget"], fields["detailed_items"]) == ("4000", "1")
    # Evidence keeps targeting as keys and counts, never names.
    assert INTEREST not in json.dumps(pending.model_dump(mode="json"))


async def test_a_lost_create_reply_is_settled_by_name_and_never_resent(monkeypatch):
    graph = AdSetGraph([campaign()], behaviour="lose_reply")

    entry, _audit = await run_tool(monkeypatch, graph, args())

    row = entry["data"]["ad_set"]
    assert len(graph.creates) == 1
    assert (row["outcome"], row["recovered"], row["adset_id"]) == ("created", True, "801")


async def test_an_eu_ad_set_without_names_or_account_defaults_fails_before_the_create(
    monkeypatch,
):
    graph = AdSetGraph([campaign()])
    france = {"locations": [{"kind": "country", "key": "FR"}]}

    entry, _audit = await run_tool(monkeypatch, graph, args(targeting=france))

    assert entry["status"] == "error"
    assert "eu_payer" in entry["error_message"]
    assert graph.creates == graph.dry_runs == []


async def test_an_eu_ad_set_inherits_the_account_defaults_and_records_it(monkeypatch):
    defaults = {"default_dsa_payor": "Agency Ltd", "default_dsa_beneficiary": "Shop Ltd"}
    graph = AdSetGraph([campaign()], account=defaults)
    france = {"locations": [{"kind": "country", "key": "FR"}]}

    entry, audit = await run_tool(monkeypatch, graph, args(targeting=france))

    (sent,) = graph.creates
    assert "dsa_payor" not in sent
    assert entry["data"]["ad_set"]["eu_transparency"] == "account_defaults"
    fields = audit.await_args_list[0].kwargs["operation_detail"].intent_groups[0].items[0].fields
    assert fields["eu_transparency"] == "account_defaults"


async def test_a_pixel_the_account_cant_use_is_refused_before_anything_is_sent(monkeypatch):
    graph = AdSetGraph([campaign()])
    other_pixel = {"account_id": "123", "pixel_id": "88", "label": "Other Pixel"}

    entry, _audit = await run_tool(monkeypatch, graph, args(pixel=other_pixel), proposed=args())

    assert entry["status"] == "error"
    assert "can't use the pixel" in entry["error_message"]
    assert graph.creates == graph.dry_runs == []


async def test_a_custom_conversion_on_another_pixel_is_refused_before_anything_is_sent(
    monkeypatch,
):
    graph = AdSetGraph([campaign()])

    entry, _audit = await run_tool(
        monkeypatch, graph, args(conversion_event=None, custom_conversion_id="300")
    )

    assert entry["status"] == "error"
    assert "another pixel" in entry["error_message"]
    assert graph.creates == graph.dry_runs == []


async def test_a_card_edit_of_status_and_targeting_is_sent_after_the_live_checks(monkeypatch):
    graph = AdSetGraph([campaign()])
    edited = {
        "locations": [
            {"kind": "country", "key": "GB"},
            {"kind": "city", "key": "2420379", "country_code": "GB"},
        ],
        "detailed": [[{"kind": "interest", "key": "600"}, {"kind": "interest", "key": "601"}]],
    }

    await run_tool(
        monkeypatch,
        graph,
        args(status="active", targeting=edited, goal="website_conversions"),
        proposed=args(),
    )

    (sent,) = graph.creates
    spec = json.loads(sent["targeting"])
    assert sent["status"] == "ACTIVE"
    assert spec["geo_locations"]["cities"] == [{"key": "2420379"}]
    assert spec["flexible_spec"] == [{"interests": [{"id": "600"}, {"id": "601"}]}]


async def test_a_goal_edited_outside_the_campaigns_objective_is_refused_live(monkeypatch):
    graph = AdSetGraph([campaign()])
    edited = args(goal="link_clicks", pixel=None, conversion_event=None)

    entry, _audit = await run_tool(monkeypatch, graph, edited, proposed=args())

    assert entry["status"] == "error"
    assert "needs a traffic campaign" in entry["error_message"]
    assert graph.creates == graph.dry_runs == []


async def test_a_campaign_changed_after_approval_is_refused(monkeypatch):
    graph = AdSetGraph([campaign(), obj("10", "campaign", objective="OUTCOME_SALES")])
    other = {**args()["campaign"], "campaign_id": "10"}

    entry, _audit = await run_tool(monkeypatch, graph, args(campaign=other), proposed=args())

    assert entry["status"] == "error"
    assert graph.creates == []


async def test_a_goal_outside_the_campaigns_objective_is_refused_before_approval():
    entry = replace(context_entry("123"), write_allowed=True)

    with pytest.raises(ModelRetry, match="needs a traffic campaign"):
        await tool_module._validate_args(
            runtime_ctx(entry), **args(goal="link_clicks", pixel=None, conversion_event=None)
        )


def _campaign(**fields) -> MetaAdsCampaignReference:
    return MetaAdsCampaignReference(
        account_id="123", campaign_id="9", label="Spring", objective="OUTCOME_SALES", **fields
    )


def test_an_ad_set_budget_under_a_campaign_budget_is_refused():
    held = {"kind": "daily", "amount": "100", "remaining": None}
    request = MetaAdsCreateAdSetRequest.model_validate(args())

    assert campaign_problems(request, _campaign(budget=held)) == [
        "This campaign holds the budget, so leave the ad set's budget out."
    ]


def test_a_bid_cap_without_a_bid_amount_is_refused():
    request = MetaAdsCreateAdSetRequest.model_validate(args())

    problems = campaign_problems(request, _campaign(bid_strategy="LOWEST_COST_WITH_BID_CAP"))

    assert problems == ["This bid strategy needs a bid_amount on the ad set."]


@pytest.mark.parametrize(
    ("overrides", "objective", "expected"),
    [
        (
            {"goal": "reach", "page": {"account_id": "123", "page_id": "11", "label": "Shop"}},
            "OUTCOME_AWARENESS",
            {"optimization_goal": "REACH", "promoted_object": '{"page_id": "11"}'},
        ),
        (
            {"goal": "link_clicks", "pay_per_click": True},
            "OUTCOME_TRAFFIC",
            {"optimization_goal": "LINK_CLICKS", "billing_event": "LINK_CLICKS"},
        ),
        (
            {
                "goal": "app_installs",
                "app": {"account_id": "123", "application_id": "55", "label": "Shop App"},
                "app_store": "google_play",
            },
            "OUTCOME_APP_PROMOTION",
            {"optimization_goal": "APP_INSTALLS"},
        ),
    ],
)
def test_each_goal_family_builds_its_meta_settings(overrides, objective, expected):
    values = {**args(pixel=None, conversion_event=None), **overrides}
    values["campaign"] = {**values["campaign"], "objective": objective}
    request = MetaAdsCreateAdSetRequest.model_validate(values)

    plan = plan_ad_set(
        request,
        request.campaign,
        campaign_id=request.campaign.campaign_id,
        currency="GBP",
        start_time=None,
        end_time=None,
        eu="not_needed",
        object_store_url="https://play.google.com/store/apps/details?id=x",
    )

    assert {key: plan.body[key] for key in expected} == expected
    assert plan.body["bid_strategy"] == "LOWEST_COST_WITHOUT_CAP"
