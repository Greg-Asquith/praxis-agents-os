# apps/api/tests/integrations/meta_ads/test_update_targeting.py

"""Targeting edits: settings Praxis can't model survive, Meta's rules hold, and stale cards fail."""

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
from integrations.meta_ads.operations.edit_targeting import edit_targeting
from integrations.meta_ads.operations.targeting_reader import (
    TARGETING_SECTIONS,
    read_targeting,
    section_fingerprints,
    write_targeting,
)
from integrations.meta_ads.references import MetaAdsAdSetReference, MetaAdsAudienceReference
from integrations.meta_ads.tools import update_targeting as tool_module
from integrations.meta_ads.tools.schemas.targeting_edits import (
    MetaAdsTargetingEdit,
    MetaAdsUpdateTargetingOutput,
    MetaAdsUpdateTargetingRequest,
)
from services.integrations.context.domain import ResolvedActiveContext
from tests.integrations.meta_ads.support import FakeGraph, context_entry, obj, static_token

_PIN = {"latitude": 51.5, "longitude": -0.12, "radius": 5, "distance_unit": "mile"}
_BUYERS = {"id": "301", "name": "Purchasers 180 days", "subtype": "WEBSITE"}
_FRANCE = {"kind": "country", "key": "FR", "name": "France"}


class TargetingGraph(FakeGraph):
    """Serves audiences and estimates, and stores posted targeting the way Meta does."""

    def handle(self, request):
        edge = request.url.path.split("/")[-1]
        if request.method == "GET" and edge == "customaudiences":
            return httpx2.Response(200, json={"data": [_BUYERS]}, request=request)
        if request.method == "GET" and edge == "reachestimate":
            spec = json.loads(request.url.params["targeting_spec"])
            people = 500_000 * len(spec["geo_locations"].get("countries", ["pin"]))
            data = {"users_lower_bound": people, "users_upper_bound": people + 50_000}
            return httpx2.Response(200, json={"data": data}, request=request)
        return super().handle(request)

    def handle_post(self, request, object_id):
        response = super().handle_post(request, object_id)
        form = dict(parse_qsl(request.content.decode()))
        if "execution_options" not in form and self.post.get(object_id, "apply") == "apply":
            item = self.objects[object_id]
            item["targeting"] = json.loads(form["targeting"])
            for key in ("dsa_payor", "dsa_beneficiary"):
                if key in form:
                    item[key] = form[key]
        return response


def _ad_set(adset_id="8", targeting=None, **fields):
    spec = targeting or {
        "geo_locations": {"countries": ["GB"], "location_types": ["home", "recent"]},
        "age_min": 18,
        "targeting_automation": {"advantage_audience": 1},
    }
    return obj(adset_id, "adset", campaign_id="9", status="ACTIVE", targeting=spec, **fields)


def _graph(*ad_sets, account=None, categories=None, **kwargs) -> TargetingGraph:
    campaign = obj("9", "campaign", status="ACTIVE", special_ad_categories=categories or [])
    return TargetingGraph(
        [campaign, *ad_sets],
        account={"default_dsa_payor": "", "default_dsa_beneficiary": "", **(account or {})},
        **kwargs,
    )


def _reference(adset_id="8", account_id="123") -> MetaAdsAdSetReference:
    return MetaAdsAdSetReference(
        account_id=account_id, campaign_id="9", adset_id=adset_id, label=f"Ad set {adset_id}"
    )


def _buyers(account_id="123") -> MetaAdsAudienceReference:
    return MetaAdsAudienceReference(
        account_id=account_id, audience_id="301", label="Purchasers 180 days", subtype="website"
    )


def _edit(adset_id="8", **changes) -> MetaAdsTargetingEdit:
    return MetaAdsTargetingEdit(ad_set=_reference(adset_id), **changes)


def _shown(graph: TargetingGraph, *ids: str) -> dict:
    """What the approval card showed: each ad set's targeting fingerprints when proposed."""
    return {
        adset_id: {"sections": section_fingerprints(graph.objects[adset_id]["targeting"])}
        for adset_id in ids
    }


def _tool_context(monkeypatch, http, *edits, checks):
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

    proposed = {"changes": [edit.model_dump(mode="json", exclude_none=True) for edit in edits]}
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
        tool_name="meta_ads_update_targeting",
        tool_call_id="call-meta-targeting",
    )
    return ctx, audit


async def _run(monkeypatch, graph, *edits, checks=None):
    http = httpx2.AsyncClient(transport=httpx2.MockTransport(graph.handle))
    ctx, audit = _tool_context(
        monkeypatch,
        http,
        *edits,
        checks=_shown(graph, *(edit.ad_set.adset_id for edit in edits))
        if checks is None
        else checks,
    )
    async with http:
        result = await tool_module.meta_ads_update_targeting(ctx, changes=list(edits))
    return result, audit


async def test_one_approval_adds_a_country_and_excludes_an_audience_keeping_a_pin(monkeypatch):
    pinned = {
        "geo_locations": {"custom_locations": [_PIN], "location_types": ["home"]},
        "age_min": 25,
        "age_max": 54,
        "excluded_geo_locations": {"countries": ["IE"]},
        "user_os": ["iOS"],
    }
    graph = _graph(_ad_set("8"), _ad_set("7", targeting=pinned))
    edits = [
        _edit("8", add_locations=[_FRANCE], eu_payer="Example Org", eu_beneficiary="Example Org"),
        _edit("7", add_excluded_audiences=[_buyers()]),
    ]

    result, audit = await _run(monkeypatch, graph, *edits)

    MetaAdsUpdateTargetingOutput.model_validate(result)
    assert graph.dry_runs == ["8", "7"] and graph.posts == ["8", "7"]
    assert graph.objects["8"]["targeting"]["geo_locations"]["countries"] == ["GB", "FR"]
    assert graph.sent[0]["dsa_payor"] == "Example Org"
    # Everything Praxis doesn't model goes back exactly as Meta returned it.
    assert graph.objects["7"]["targeting"] == {
        **pinned,
        "excluded_custom_audiences": [{"id": "301"}],
    }
    rows = result["results"][0]["data"]["ad_sets"]
    assert [row["outcome"] for row in rows] == ["updated", "updated"]
    assert rows[0]["changes"] == [
        {
            "section": "locations",
            "before": "country:GB; home_or_recent",
            "requested": "country:FR,country:GB; home_or_recent",
            "after": "country:FR,country:GB; home_or_recent",
        }
    ]
    # Evidence holds keys and counts, never audience or interest names.
    pending = audit.await_args_list[0].kwargs["operation_detail"].intent_groups[0].items[1]
    assert pending.fields["operations"] == {"add_excluded_audiences": 1}
    assert pending.fields["requested"] == {"excluded_audiences": "301"}
    assert "Purchasers" not in json.dumps(pending.fields)


async def test_a_location_edit_on_an_ad_set_with_a_pin_is_refused_before_anything_is_sent(
    monkeypatch,
):
    pinned = {"geo_locations": {"custom_locations": [_PIN]}, "age_min": 18}
    graph = _graph(_ad_set("7", targeting=pinned))

    result, _audit = await _run(monkeypatch, graph, _edit("7", add_locations=[_FRANCE]))

    assert graph.dry_runs == [] and graph.posts == []
    assert "locations include pins" in result["results"][0]["error_message"]


async def test_a_section_that_changed_after_approval_is_not_sent(monkeypatch):
    graph = _graph(_ad_set("8"), _ad_set("7"))
    edits = [_edit("8", genders="women"), _edit("7", genders="women")]
    shown = _shown(graph, "8", "7")
    # Someone narrowed ad set 8 to men in Ads Manager after the card was shown.
    graph.objects["8"]["targeting"] = {**graph.objects["8"]["targeting"], "genders": [1]}

    result, _audit = await _run(monkeypatch, graph, *edits, checks=shown)

    stale, kept = result["results"][0]["data"]["ad_sets"]
    assert graph.posts == ["7"]
    assert (stale["outcome"], stale["error_code"]) == ("failed", "CHANGED_SINCE_APPROVAL")
    assert kept["outcome"] == "updated"


async def test_an_audience_the_ad_account_cant_use_is_refused(monkeypatch):
    graph = _graph(_ad_set("8"))
    stranger = MetaAdsAudienceReference(account_id="123", audience_id="999", label="Lookalike")

    result, _audit = await _run(monkeypatch, graph, _edit("8", add_audiences=[stranger]))

    assert graph.dry_runs == [] and graph.posts == []
    assert "can't use Lookalike" in result["results"][0]["error_message"]


def test_an_audience_from_another_ad_account_is_refused():
    with pytest.raises(ValueError, match="ad set's ad account"):
        _edit("8", add_excluded_audiences=[_buyers(account_id="555")])


def test_reading_and_rewriting_every_modelled_section_gives_the_same_spec():
    spec = {
        "geo_locations": {"custom_locations": [_PIN], "location_types": ["home"]},
        "excluded_geo_locations": {
            "countries": ["IE"],
            "cities": [{"key": "2421836", "radius": 10, "distance_unit": "mile"}],
            "zips": [{"key": "GB:SW1A"}],
        },
        "age_min": 25,
        "age_max": 54,
        "genders": [2],
        "locales": [6, 24],
        "flexible_spec": [
            {"interests": [{"id": "6003"}], "family_statuses": [{"id": "6002714398172"}]},
            {"behaviors": [{"id": "6015559470583"}]},
        ],
        "custom_audiences": [{"id": "301"}],
        "excluded_custom_audiences": [{"id": "302"}],
        "targeting_automation": {"advantage_audience": 0},
        "publisher_platforms": ["facebook"],
    }

    read = read_targeting(spec, account_id="123")
    modelled = [section for section in TARGETING_SECTIONS if section not in read.unmodelled]

    assert list(read.unmodelled) == ["locations"]
    assert write_targeting(read, read.draft, modelled) == spec


@pytest.mark.parametrize(
    ("changes", "categories", "account", "problem"),
    [
        ({"remove_locations": [{"kind": "country", "key": "IE"}]}, [], {}, "IE isn't targeted"),
        ({"genders": "women"}, ["HOUSING"], {}, "can't target by gender"),
        ({"add_locations": [_FRANCE]}, [], {}, "eu_payer and eu_beneficiary"),
    ],
)
def test_changes_meta_would_refuse_are_named_before_approval(changes, categories, account, problem):
    spec = {"geo_locations": {"countries": ["GB"]}, "age_min": 18}
    change = edit_targeting(
        _edit("8", **changes),
        read_targeting(spec, account_id="123"),
        special_category=bool(categories),
        reached_eu=False,
        has_eu_names=False,
        eu_defaults=bool(account),
    )

    assert any(problem in item for item in change.problems)


def test_retired_placements_are_dropped_with_a_note_before_any_write():
    spec = {
        "geo_locations": {"countries": ["GB"]},
        "age_min": 30,
        "publisher_platforms": ["facebook", "instagram"],
        "instagram_positions": ["stream", "explore"],
    }

    change = edit_targeting(
        _edit("8", age_min=35),
        read_targeting(spec, account_id="123"),
        special_category=False,
        reached_eu=False,
        has_eu_names=False,
        eu_defaults=False,
    )

    assert change.problems == []
    assert change.spec["instagram_positions"] == ["stream"]
    assert any("Instagram Explore" in note for note in change.notes)


def test_the_card_can_add_places_and_audiences_but_no_other_change():
    proposed = {"changes": [_edit("8", genders="women").model_dump(mode="json")]}
    from_card = _edit("8", genders="men", add_locations=[_FRANCE], add_audiences=[_buyers()])

    tool_module._require_proposed(proposed, _request(from_card))

    interest = {"kind": "interest", "key": "6003", "name": "Running"}
    for added in (
        _edit("8", genders="women", age_min=30),
        _edit("8", genders="women", add_detailed_items={"group": 1, "items": [interest]}),
        _edit("7", add_locations=[_FRANCE]),
    ):
        with pytest.raises(ModelRetry, match="added after approval"):
            tool_module._require_proposed(proposed, _request(added))


def _request(*edits: MetaAdsTargetingEdit) -> MetaAdsUpdateTargetingRequest:
    return MetaAdsUpdateTargetingRequest(changes=list(edits))
