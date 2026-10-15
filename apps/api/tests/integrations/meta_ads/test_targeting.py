# apps/api/tests/integrations/meta_ads/test_targeting.py

"""Meta targeting: the typed draft's mapping and local rules, search, estimates, and audiences."""

import json
from types import SimpleNamespace

import httpx2

from integrations.meta_ads.client import MetaAdsClient
from integrations.meta_ads.entity_resolvers.audience import resolve_meta_ads_audiences
from integrations.meta_ads.entity_resolvers.targeting import (
    MetaAdsInterestOption,
    resolve_interests,
    search_interests,
    search_locations,
)
from integrations.meta_ads.operations.estimate_audience import estimate_audience
from integrations.meta_ads.operations.search_targeting import search_targeting
from integrations.meta_ads.operations.targeting import (
    MetaAdsTargeting,
    targeting_problems,
    targeting_spec,
)
from integrations.meta_ads.references import MetaAdsAudienceReference
from services.integrations.context.domain import ResolvedActiveContext
from tests.integrations.meta_ads.support import context_entry, static_token

BUYERS = MetaAdsAudienceReference(
    account_id="123", audience_id="44", label="Buyers", subtype="lookalike"
)


def draft(**overrides) -> MetaAdsTargeting:
    return MetaAdsTargeting.model_validate(
        {"locations": [{"kind": "country", "key": "GB"}], **overrides}
    )


async def call(handler, operation, **kwargs):
    async with httpx2.AsyncClient(transport=httpx2.MockTransport(handler)) as http:
        return await operation(MetaAdsClient(static_token, client=http), account_id="123", **kwargs)


def test_full_draft_maps_to_meta_spec_with_advantage_audience_stated():
    targeting = draft(
        locations=[
            {"kind": "country", "key": "GB"},
            {"kind": "city", "key": "2421178", "radius": 20, "radius_unit": "kilometer"},
        ],
        excluded_locations=[{"kind": "postcode", "key": "GB:SW1A"}],
        location_types="home",
        age_min=25,
        age_max=54,
        genders="women",
        languages=["24"],
        detailed=[
            [
                {"kind": "interest", "key": "6003", "name": "Running"},
                {"kind": "demographic", "key": "6002", "category": "life_events"},
            ],
            [{"kind": "behavior", "key": "6015"}],
        ],
        audiences=[BUYERS.model_dump()],
        advantage_audience=False,
    )

    assert targeting_spec(targeting) == {
        "geo_locations": {
            "countries": ["GB"],
            "cities": [{"key": "2421178", "radius": 20, "distance_unit": "kilometer"}],
            "location_types": ["home"],
        },
        "excluded_geo_locations": {"zips": [{"key": "GB:SW1A"}]},
        "age_min": 25,
        "age_max": 54,
        "genders": [2],
        "locales": [24],
        "flexible_spec": [
            {"interests": [{"id": "6003"}], "life_events": [{"id": "6002"}]},
            {"behaviors": [{"id": "6015"}]},
        ],
        "custom_audiences": [{"id": "44"}],
        "targeting_automation": {"advantage_audience": 0},
    }


def test_advantage_audience_refuses_a_fixed_age_range():
    problems = targeting_problems(draft(age_min=25, age_max=54), special_category=False)

    assert len(problems) == 1 and "advantage_audience" in problems[0]
    assert targeting_problems(draft(age_min=25), special_category=False) == []


def test_special_category_refuses_gender_targeting():
    targeting = draft(genders="men", advantage_audience=False)

    assert targeting_problems(targeting, special_category=False) == []
    assert len(targeting_problems(targeting, special_category=True)) == 1


def test_special_category_refuses_postcodes():
    targeting = draft(locations=[{"kind": "postcode", "key": "US:94304"}])

    assert targeting_problems(targeting, special_category=True) == [
        "Housing, employment, and financial ads can't target postcodes."
    ]


async def test_interest_search_returns_keys_and_meta_size_range():
    requests: list[httpx2.Request] = []

    def graph(request: httpx2.Request) -> httpx2.Response:
        requests.append(request)
        rows = [
            {
                "id": "6003",
                "name": "Running",
                "path": ["Interests", "Fitness and wellness", "Running"],
                "audience_size_lower_bound": 410_000_000,
                "audience_size_upper_bound": 482_000_000,
            },
            {"id": "6004", "name": "Trail running"},
        ]
        return httpx2.Response(200, json={"data": rows}, request=request)

    result = await call(
        graph, search_targeting, kind="interest", query="running", country_code=None, limit=1
    )

    assert requests[0].url.path.endswith("/search")
    assert dict(requests[0].url.params) == {"q": "running", "limit": "2", "type": "adinterest"}
    (running,) = result.options
    assert (running.key, running.description) == ("6003", "Interests > Fitness and wellness")
    assert (
        running.audience_size_range is not None and running.audience_size_range.lower == 410_000_000
    )
    assert result.truncated is True


async def test_demographic_search_matches_by_name_and_keeps_usable_categories():
    def graph(request: httpx2.Request) -> httpx2.Response:
        rows = [
            {"id": "1", "name": "New parents (0-12 months)", "type": "family_statuses"},
            {"id": "2", "name": "Parents with teenagers", "type": "family_statuses"},
            {"id": "3", "name": "Parents (all)", "type": "education_statuses"},
            {"id": "4", "name": "Newly engaged", "type": "life_events"},
        ]
        return httpx2.Response(200, json={"data": rows}, request=request)

    result = await call(
        graph, search_targeting, kind="demographic", query="parents", country_code=None, limit=20
    )

    assert [(option.key, option.category) for option in result.options] == [
        ("1", "family_statuses"),
        ("2", "family_statuses"),
    ]


async def test_estimate_sends_the_mapped_spec_and_reports_no_estimate_as_null():
    sent: dict[str, object] = {}

    def graph(request: httpx2.Request) -> httpx2.Response:
        sent["path"] = request.url.path
        sent["spec"] = json.loads(request.url.params["targeting_spec"])
        data = {"users_lower_bound": -1, "users_upper_bound": -1, "estimate_ready": True}
        return httpx2.Response(200, json={"data": data}, request=request)

    targeting = draft(age_min=21)
    result = await call(graph, estimate_audience, targeting=targeting)

    assert str(sent["path"]).endswith("/act_123/reachestimate")
    assert sent["spec"] == targeting_spec(targeting)
    assert (result.users_lower_bound, result.users_upper_bound) == (None, None)
    assert len(result.notes) == 1


async def test_audience_resolver_refuses_an_audience_the_account_does_not_list(monkeypatch):
    paths: list[str] = []

    def graph(request: httpx2.Request) -> httpx2.Response:
        paths.append(request.url.path)
        rows = [{"id": "45", "name": "Newsletter", "subtype": "CUSTOM"}]
        return httpx2.Response(200, json={"data": rows}, request=request)

    http = httpx2.AsyncClient(transport=httpx2.MockTransport(graph))

    async def client(*_args, **_kwargs):
        return MetaAdsClient(static_token, client=http)

    monkeypatch.setattr(
        "integrations.meta_ads.entity_resolvers.utils.meta_ads_client_for_principal", client
    )
    ctx = SimpleNamespace(
        active_context=ResolvedActiveContext(entries=(context_entry("123"),)),
        db=None,
        actor=None,
        workspace=None,
    )
    # Audience 44 belongs to another account the token can read; 999 isn't selected at all.
    foreign = BUYERS.model_copy(update={"account_id": "999"})

    async with http:
        choices = await resolve_meta_ads_audiences(
            ctx, [BUYERS.model_dump(mode="json"), foreign.model_dump(mode="json")], None
        )

    assert choices == ()
    assert paths and all(path.split("/")[2] == "act_123" for path in paths)


async def test_place_and_interest_lookups_give_values_a_card_can_add_to_targeting(monkeypatch):
    def graph(request: httpx2.Request) -> httpx2.Response:
        params = request.url.params
        if params["type"] == "adinterest":
            rows = [{"id": "600", "name": "Running", "audience_size_lower_bound": 1}]
        elif "city" in params["location_types"]:
            row = {"type": "city", "key": "2420379", "name": "London", "country_code": "GB"}
            rows = [row, {"type": "region", "key": "9", "name": "London"}]
        else:
            rows = []
        return httpx2.Response(200, json={"data": rows}, request=request)

    http = httpx2.AsyncClient(transport=httpx2.MockTransport(graph))

    async def client(*_args, **_kwargs):
        return MetaAdsClient(static_token, client=http)

    monkeypatch.setattr(
        "integrations.meta_ads.entity_resolvers.targeting.meta_ads_client_for_principal", client
    )
    ctx = SimpleNamespace(
        active_context=ResolvedActiveContext(entries=(context_entry("123"),)),
        db=None,
        actor=None,
        workspace=None,
    )

    async with http:
        places = await search_locations(ctx, "London", {}, 25, None)
        interests = await search_interests(ctx, "Running", {}, 25, None)
        stale = MetaAdsInterestOption(account_id="123", key="601", label="Running", name="Running")
        confirmed = await resolve_interests(ctx, [stale.model_dump(mode="json")], {})

    (city,) = [choice.value for choice in places.choices if choice.value["kind"] == "city"]
    (interest,) = [choice.value for choice in interests.choices]
    item = ("kind", "key", "name", "country_code")
    targeting = draft(
        locations=[{k: city[k] for k in item}],
        detailed=[[{k: interest[k] for k in ("kind", "key", "name")}]],
    )
    assert targeting.locations[0].key == "2420379"
    assert targeting.detailed[0][0].key == "600"
    # Meta didn't return key 601 for that name, so the reference doesn't hydrate.
    assert confirmed == ()
