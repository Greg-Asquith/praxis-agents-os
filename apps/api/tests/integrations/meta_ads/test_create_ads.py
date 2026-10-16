# apps/api/tests/integrations/meta_ads/test_create_ads.py

"""Meta ad creation: rules before approval, dry runs before anything is created, and proof after."""

import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock
from urllib.parse import parse_qsl
from uuid import uuid4

import httpx2
import pytest
from pydantic import ValidationError

from core.exceptions.general import NotFoundError
from core.exceptions.integration import IntegrationFailureDisposition
from integrations.meta_ads.models import MetaAdsPlacements
from integrations.meta_ads.operations.media_source import MediaSource
from integrations.meta_ads.operations.mutations import (
    MetaAdsMutationEffect,
    MetaAdsMutationLedger,
    MetaAdsMutationParent,
)
from integrations.meta_ads.operations.plan_ads import design_problem, plan_ads
from integrations.meta_ads.operations.upload_media import MediaUpload
from integrations.meta_ads.references import (
    MetaAdsAdSetReference,
    MetaAdsInstagramAccountReference,
    MetaAdsMediaReference,
    MetaAdsPageReference,
    MetaAdsPostReference,
)
from integrations.meta_ads.tools import create_ads as tool_module
from integrations.meta_ads.tools.create_ads import meta_ads_create_ads
from integrations.meta_ads.tools.schemas.ads import (
    MetaAdsAdDesign,
    MetaAdsCreateAdsOutput,
    MetaAdsCreateAdsRequest,
)
from integrations.meta_ads.tools.utils import ad_preparation as preparation_module
from services.integrations.files import FileReference
from tests.integrations.meta_ads.support import (
    FakeGraph,
    obj,
    write_tool_context,
)

PAGE = MetaAdsPageReference(account_id="123", page_id="11", label="Acme")
IMAGE = MetaAdsMediaReference(
    account_id="123", media_type="image", image_hash="abc", label="hero.jpg", media_status="ready"
)
INSTAGRAM = MetaAdsInstagramAccountReference(
    account_id="123", instagram_user_id="22", label="@acme"
)
FACEBOOK_POST = MetaAdsPostReference(
    account_id="123", source="facebook", post_id="11_500", page_id="11", label="Facebook post"
)
INSTAGRAM_POST = MetaAdsPostReference(
    account_id="123",
    source="instagram",
    post_id="700",
    instagram_user_id="22",
    label="Instagram post",
    boostable=True,
)


def ad_set(adset_id: str, **values) -> MetaAdsAdSetReference:
    return MetaAdsAdSetReference(
        account_id="123", campaign_id="9", adset_id=adset_id, label=f"adset {adset_id}", **values
    )


def design(name: str = "Spring", ad_sets=("8",), **values) -> MetaAdsAdDesign:
    return MetaAdsAdDesign(
        name=name,
        ad_sets=[ad_set(adset_id) for adset_id in ad_sets],
        primary_text="Spring sale on now",
        **{"format": "image", "headline": "20% off", "media": IMAGE, **values},
    )


def request(*designs: MetaAdsAdDesign, **values) -> MetaAdsCreateAdsRequest:
    return MetaAdsCreateAdsRequest(
        ads=list(designs) or [design()],
        page=values.pop("page", PAGE),
        link=values.pop("link", "https://shop.example.com/spring"),
        **values,
    )


class AdsGraph(FakeGraph):
    """Serves the account's assets and ads edge, and creates ads from posted creatives."""

    def __init__(self, objects, *, behaviour=None, turn_on=None, boostable=True):
        super().__init__(objects)
        self.boostable = boostable
        self.behaviour = behaviour or {}
        self.turn_on = turn_on or {}
        self.creates: list[dict[str, str]] = []
        self.dry_run_names: list[str] = []
        self.next_id = 900

    def handle(self, request: httpx2.Request) -> httpx2.Response:
        path = request.url.path.split("/")[2:]
        if request.method == "POST" and path == ["act_123", "ads"]:
            return self.post_ad(request)
        edge = path[1] if len(path) > 1 else None
        rows = {
            "promote_pages": [{"id": "11", "name": "Acme"}],
            "connected_instagram_accounts": [{"id": "22", "username": "acme"}],
            "adimages": [{"hash": "abc", "name": "hero.jpg", "status": "ACTIVE"}],
            "advideos": [],
            "published_posts": [{"id": "11_500", "message": "Our best day"}],
            "media": [
                {
                    "id": "700",
                    "caption": "Summer drop",
                    "media_type": "IMAGE",
                    "boost_eligibility_info": {"eligible_to_boost": self.boostable},
                }
            ],
        }.get(edge)
        if rows is not None:
            return httpx2.Response(200, json={"data": rows}, request=request)
        return super().handle(request)

    def post_ad(self, request: httpx2.Request) -> httpx2.Response:
        form = dict(parse_qsl(request.content.decode()))
        behaviour = self.behaviour.get(form["name"], "apply")
        if "execution_options" in form:
            self.dry_run_names.append(form["name"])
            if behaviour == "reject_dry_run":
                error = {"code": 100, "error_user_msg": "Text is too long.", "fbtrace_id": "t"}
                return httpx2.Response(400, json={"error": error}, request=request)
            return httpx2.Response(200, json={"success": True}, request=request)
        self.creates.append(form)
        if behaviour == "reject":
            error = {"code": 100, "error_user_msg": "Image too small.", "fbtrace_id": "t"}
            return httpx2.Response(400, json={"error": error}, request=request)
        ad_id = str(self.next_id)
        self.next_id += 1
        creative = {"id": f"5{ad_id}", **json.loads(form["creative"])}
        for feature in self.turn_on.get(form["name"], ()):
            features = creative["degrees_of_freedom_spec"]["creative_features_spec"]
            features[feature] = {"enroll_status": "OPT_IN"}
        self.objects[ad_id] = obj(
            ad_id,
            "ad",
            name=form["name"],
            adset_id=form["adset_id"],
            campaign_id="9",
            status=form["status"],
            effective_status="PENDING_REVIEW",
            created_time="2099-01-01T00:00:00+0000",
            creative=creative,
            preview_shareable_link="https://fb.me/preview",
        )
        if behaviour == "lose_reply":
            raise httpx2.ReadTimeout("lost", request=request)
        return httpx2.Response(200, json={"id": ad_id}, request=request)


def live_ad_sets(*adset_ids: str, **values):
    return [obj(adset_id, "adset", campaign_id="9", **values) for adset_id in adset_ids]


def tool_context(monkeypatch, http: httpx2.AsyncClient, reviewed: dict, proposed: dict):
    return write_tool_context(
        monkeypatch,
        http,
        tool_name="meta_ads_create_ads",
        proposed=proposed,
        reviewed=reviewed,
        tool_modules=(tool_module, preparation_module),
    )


async def run_tool(
    monkeypatch, graph: AdsGraph, call: MetaAdsCreateAdsRequest, reviewed=None, proposed=None
):
    http = httpx2.AsyncClient(transport=httpx2.MockTransport(graph.handle))
    ctx, audit = tool_context(
        monkeypatch, http, reviewed or {}, (proposed or call).model_dump(mode="json")
    )
    async with http:
        result = await meta_ads_create_ads(ctx, **dict(call))
    MetaAdsCreateAdsOutput.model_validate(result)
    return result["results"][0], audit


async def test_every_ad_is_checked_then_created_paused_with_hashed_evidence(monkeypatch):
    graph = AdsGraph(live_ad_sets("8", "7"))

    entry, audit = await run_tool(monkeypatch, graph, request(design(ad_sets=("8", "7"))))

    names = ["Spring | adset 8", "Spring | adset 7"]
    assert graph.dry_run_names == names
    assert [form["name"] for form in graph.creates] == names
    assert {form["status"] for form in graph.creates} == {"PAUSED"}
    rows = entry["data"]["ads"]
    assert [(row["outcome"], row["review"]) for row in rows] == [("created", "in_review")] * 2
    assert rows[0]["preview_url"] == "https://fb.me/preview"
    pending, terminal = (call.kwargs for call in audit.await_args_list)
    intent = pending["operation_detail"].intent_groups[0].items[0].fields
    # Evidence names the link's domain and hashes the public text; it never holds the text.
    assert intent["link_domain"] == "shop.example.com"
    assert "primary_text_sha256" in intent and "headline_sha256" in intent
    assert "Spring sale" not in json.dumps(pending["operation_detail"].model_dump(mode="json"))
    assert terminal["status"] == "success"


async def test_a_dry_run_rejection_creates_nothing(monkeypatch):
    graph = AdsGraph(live_ad_sets("8"), behaviour={"Autumn": "reject_dry_run"})

    entry, _audit = await run_tool(monkeypatch, graph, request(design("Spring"), design("Autumn")))

    assert graph.dry_run_names == ["Spring", "Autumn"]
    assert graph.creates == []
    assert entry["status"] == "error"
    assert "Autumn: Text is too long." in entry["error_message"]


async def test_later_ads_continue_after_one_fails(monkeypatch):
    graph = AdsGraph(live_ad_sets("8"), behaviour={"Spring": "reject"})

    entry, audit = await run_tool(monkeypatch, graph, request(design("Spring"), design("Autumn")))

    rows = {row["name"]: row for row in entry["data"]["ads"]}
    assert rows["Spring"]["outcome"] == "failed"
    assert rows["Autumn"]["outcome"] == "created"
    assert audit.await_args_list[-1].kwargs["status"] == "partial"


async def test_a_lost_reply_is_settled_by_name_and_never_resent(monkeypatch):
    graph = AdsGraph(live_ad_sets("8"), behaviour={"Spring": "lose_reply"})

    entry, _audit = await run_tool(monkeypatch, graph, request())

    (row,) = entry["data"]["ads"]
    assert len(graph.creates) == 1
    assert (row["outcome"], row["recovered"], row["ad_id"]) == ("created", True, "900")


async def test_a_change_meta_turned_on_that_was_left_off_marks_the_ad(monkeypatch):
    graph = AdsGraph(live_ad_sets("8"), turn_on={"Spring": ["inline_comment"]})

    entry, _audit = await run_tool(monkeypatch, graph, request())

    (row,) = entry["data"]["ads"]
    assert row["outcome"] == "created"
    assert row["unexpected_changes"] == ["Relevant comments"]
    assert "Meta turned on automatic changes" in row["message"]


async def test_an_ad_set_changed_on_the_card_is_re_read_and_used(monkeypatch):
    graph = AdsGraph(live_ad_sets("8", "7"))
    approved = request(design(ad_sets=("8",)))

    entry, _audit = await run_tool(
        monkeypatch, graph, request(design(ad_sets=("7",))), proposed=approved
    )

    assert entry["data"]["ads"][0]["outcome"] == "created"
    assert [form["adset_id"] for form in graph.creates] == ["7"]


async def test_an_ad_set_outside_the_account_is_refused_after_a_card_edit(monkeypatch):
    graph = AdsGraph(live_ad_sets("8"))
    approved = request(design(ad_sets=("8",)))

    entry, _audit = await run_tool(
        monkeypatch, graph, request(design(ad_sets=("7",))), proposed=approved
    )

    assert entry["status"] == "error"
    assert graph.creates == [] and graph.dry_run_names == []


async def test_ads_fixed_on_the_card_run_although_the_proposal_broke_a_rule(monkeypatch):
    graph = AdsGraph(live_ad_sets("8"))
    proposed = request().model_dump(mode="json")
    # The card removed what the proposal got wrong; only its ad sets are compared.
    proposed["ads"][0]["headline"] = None

    http = httpx2.AsyncClient(transport=httpx2.MockTransport(graph.handle))
    ctx, _audit = tool_context(monkeypatch, http, {}, proposed)
    async with http:
        result = await meta_ads_create_ads(ctx, **dict(request()))

    assert result["results"][0]["status"] == "success"
    assert [form["name"] for form in graph.creates] == ["Spring"]


def sent_link(form: dict[str, str]) -> str:
    return json.loads(form["creative"])["object_story_spec"]["link_data"]["link"]


async def test_an_ad_that_copied_the_shared_link_follows_a_shared_edit(monkeypatch):
    graph = AdsGraph(live_ad_sets("8"))
    old, new = "https://shop.example.com/spring", "https://shop.example.com/summer"
    proposed = request(design(link=old), link=old)

    entry, _audit = await run_tool(
        monkeypatch, graph, request(design(link=old), link=new), proposed=proposed
    )

    assert entry["status"] == "success"
    assert [sent_link(form) for form in graph.creates] == [new]


async def test_an_ads_own_link_set_on_the_card_is_kept(monkeypatch):
    graph = AdsGraph(live_ad_sets("8"))
    old, new = "https://shop.example.com/spring", "https://shop.example.com/summer"
    proposed = request(design(), link=old)

    # The operator moved the shared link on and kept this ad on the old one.
    entry, _audit = await run_tool(
        monkeypatch, graph, request(design(link=old), link=new), proposed=proposed
    )

    assert entry["status"] == "success"
    assert [sent_link(form) for form in graph.creates] == [old]


async def test_media_swapped_on_the_card_is_reread_through_the_account(monkeypatch):
    graph = AdsGraph(live_ad_sets("8"))
    proposed = request()
    # Same account on the reference, but the hash isn't in this ad account's library.
    elsewhere = IMAGE.model_copy(update={"image_hash": "fromanotheraccount"})

    entry, _audit = await run_tool(
        monkeypatch, graph, request(design(media=elsewhere)), proposed=proposed
    )

    assert entry["status"] == "error"
    assert "no longer in this ad account's media library" in entry["error_message"]
    assert graph.creates == [] and graph.dry_run_names == []


async def test_a_video_from_another_account_is_refused(monkeypatch):
    graph = AdsGraph(live_ad_sets("8"))
    video = MetaAdsMediaReference(
        account_id="123", media_type="video", video_id="555", label="clip", media_status="ready"
    )
    call = request(design(format="video", media=video, thumbnail=IMAGE))

    entry, _audit = await run_tool(monkeypatch, graph, call, proposed=request())

    assert "isn't among the 500 most recent videos" in entry["error_message"]
    assert graph.creates == [] and graph.dry_run_names == []


async def test_a_page_the_account_cant_advertise_as_is_refused(monkeypatch):
    graph = AdsGraph(live_ad_sets("8"))
    elsewhere = MetaAdsPageReference(account_id="123", page_id="99", label="Other Page")

    entry, _audit = await run_tool(monkeypatch, graph, request(page=elsewhere))

    assert entry["status"] == "error"
    assert "can't advertise as the Page" in entry["error_message"]
    assert graph.creates == [] and graph.dry_run_names == []


async def test_an_approval_for_another_selection_of_the_account_is_refused(monkeypatch):
    graph = AdsGraph(live_ad_sets("8"))
    stale_pin = {"account_id": "123", "resource_id": str(uuid4())}

    entry, _audit = await run_tool(monkeypatch, graph, request(), reviewed={"_account": stale_pin})

    assert entry["status"] == "error"
    assert "no longer selected" in entry["error_message"]
    assert graph.creates == [] and graph.dry_run_names == []


async def test_an_ad_set_cant_go_over_metas_fifty_ads(monkeypatch):
    existing = [obj(str(100 + index), "ad", adset_id="8", campaign_id="9") for index in range(49)]
    graph = AdsGraph([*live_ad_sets("8"), *existing])

    entry, _audit = await run_tool(monkeypatch, graph, request(design("Spring"), design("Autumn")))

    assert entry["status"] == "error"
    assert "50 ads per ad set" in entry["error_message"]
    assert graph.creates == []


def test_an_ai_generated_change_creates_every_ad_off():
    call = request(design(status="active"), automatic_changes=["image_uncrop"], status="active")

    assert {ad.status for ad in plan_ads(call, {})} == {"paused"}
    assert {ad.status for ad in plan_ads(request(design(status="active")), {})} == {"active"}


def test_buttons_follow_the_goal():
    app_ad_set = ad_set("8", objective="OUTCOME_APP_PROMOTION")
    call = request(design(call_to_action="SHOP_NOW"))

    assert "isn't available for this ad set's goal" in design_problem(
        call.ads[0], call, [app_ad_set]
    )
    assert design_problem(call.ads[0], call, [ad_set("8")]) is None


def test_dynamic_creative_ad_sets_are_refused():
    call = request(design())
    dynamic = ad_set("8", is_dynamic_creative=True)

    assert "dynamic creative" in design_problem(call.ads[0], call, [dynamic])


def test_a_vertical_version_needs_an_ad_set_that_shows_stories_or_reels():
    call = request(design(vertical_media=IMAGE))
    feed_only = ad_set(
        "8", placements=MetaAdsPlacements(mode="manual", positions=["facebook:feed"])
    )
    stories = ad_set(
        "8", placements=MetaAdsPlacements(mode="manual", positions=["instagram:story"])
    )

    assert "Stories or Reels" in design_problem(call.ads[0], call, [feed_only])
    assert design_problem(call.ads[0], call, [stories]) is None


def post_design(post: MetaAdsPostReference, **values) -> MetaAdsAdDesign:
    return MetaAdsAdDesign(
        name="Best post", ad_sets=[ad_set("8")], format="existing_post", post=post, **values
    )


async def test_a_facebook_post_is_checked_then_created_as_it_is(monkeypatch):
    graph = AdsGraph(live_ad_sets("8"))

    entry, _audit = await run_tool(monkeypatch, graph, request(post_design(FACEBOOK_POST)))

    assert entry["status"] == "success"
    assert graph.dry_run_names == ["Best post"]
    (form,) = graph.creates
    assert json.loads(form["creative"])["object_story_id"] == "11_500"


async def test_an_instagram_post_meta_wont_boost_is_refused_before_any_create(monkeypatch):
    graph = AdsGraph(live_ad_sets("8"), boostable=False)
    call = request(post_design(INSTAGRAM_POST), instagram_account=INSTAGRAM)

    entry, _audit = await run_tool(monkeypatch, graph, call)

    assert entry["status"] == "error"
    assert "no longer allows" in entry["error_message"]
    assert graph.creates == [] and graph.dry_run_names == []


async def test_a_post_its_page_didnt_publish_is_refused(monkeypatch):
    graph = AdsGraph(live_ad_sets("8"))
    # The Page is the account's own, but this post isn't among its posts.
    elsewhere = FACEBOOK_POST.model_copy(update={"post_id": "11_999"})

    entry, _audit = await run_tool(monkeypatch, graph, request(post_design(elsewhere)))

    assert entry["status"] == "error"
    assert "isn't among the 100 most recent posts" in entry["error_message"]
    assert graph.creates == [] and graph.dry_run_names == []


def test_an_existing_post_refuses_text_and_media():
    with pytest.raises(ValidationError, match="runs as it is"):
        post_design(FACEBOOK_POST, primary_text="New words", media=IMAGE)
    with pytest.raises(ValidationError, match="keeps its own link"):
        post_design(FACEBOOK_POST, link="https://shop.example.com/")


def test_links_must_be_https_without_credentials():
    with pytest.raises(ValidationError, match="https"):
        request(link="http://example.com")
    with pytest.raises(ValidationError, match="https"):
        request(link="https://user:secret@example.com")


def file_source() -> MediaSource:
    revision = SimpleNamespace(
        id=uuid4(), content_hash="sha", size_bytes=10, content_type="image/png", extension=".png"
    )
    return MediaSource(SimpleNamespace(id=uuid4(), name="spring.png"), revision, "image")


async def run_with_file(monkeypatch, graph: AdsGraph, uploaded_hash: str | None):
    source = file_source()
    monkeypatch.setattr(preparation_module, "resolve_media_source", AsyncMock(return_value=source))

    async def upload(_client, *, sources, **_values):
        effect = MetaAdsMutationEffect(
            fields=(("media_type", "image"),),
            outcome="applied" if uploaded_hash else "failed",
            external_ref=uploaded_hash,
            error_code=None if uploaded_hash else "UPLOAD_FAILED",
            message=None if uploaded_hash else "Meta rejected the image.",
        )
        item = MediaUpload(sources[0], media_id=uploaded_hash, effect=effect)
        parent = MetaAdsMutationParent(
            identity=(("file_id", item.file_id),), decision="submit", effects=(effect,)
        )
        return [item], MetaAdsMutationLedger(action="upload_media", parents=(parent,))

    monkeypatch.setattr("integrations.meta_ads.operations.create_ads.upload_media", upload)
    file_image = FileReference(entity_id=source.file.id, label="spring.png")
    call = request(design("Library"), design("From File", media=file_image))
    reviewed = {"_files": [source.approval_details()]}
    return await run_tool(monkeypatch, graph, call, reviewed=reviewed)


async def test_a_file_image_is_uploaded_then_checked_with_its_new_hash(monkeypatch):
    graph = AdsGraph(live_ad_sets("8"))

    entry, _audit = await run_with_file(monkeypatch, graph, "f1hash")

    # The library ad is checked before approval runs; the File's ad once its image exists.
    assert graph.dry_run_names == ["Library", "From File"]
    sent = {form["name"]: json.loads(form["creative"]) for form in graph.creates}
    assert sent["From File"]["object_story_spec"]["link_data"]["image_hash"] == "f1hash"
    assert entry["data"]["uploads"][0]["outcome"] == "uploaded"


async def test_an_ad_whose_image_didnt_upload_is_never_sent(monkeypatch):
    graph = AdsGraph(live_ad_sets("8"))

    entry, audit = await run_with_file(monkeypatch, graph, None)

    rows = {row["name"]: row for row in entry["data"]["ads"]}
    assert [form["name"] for form in graph.creates] == ["Library"]
    assert (rows["From File"]["outcome"], rows["From File"]["error_code"]) == (
        "failed",
        "MEDIA_NOT_UPLOADED",
    )
    assert audit.await_args_list[-1].kwargs["status"] == "partial"


async def test_a_cancel_after_ads_were_created_is_ambiguous_with_full_evidence(monkeypatch):
    graph = AdsGraph(live_ad_sets("8"))

    def cancel_read_back(request: httpx2.Request) -> httpx2.Response:
        if request.method == "GET" and request.url.path.endswith("/ads") and graph.creates:
            raise asyncio.CancelledError
        return graph.handle(request)

    call = request()
    http = httpx2.AsyncClient(transport=httpx2.MockTransport(cancel_read_back))
    ctx, _audit = tool_context(monkeypatch, http, {}, call.model_dump(mode="json"))
    with pytest.raises(asyncio.CancelledError) as cancelled:
        async with http:
            await meta_ads_create_ads(ctx, **dict(call))

    # The ad exists, so the run must never report that nothing was sent.
    assert cancelled.value.failure_disposition is IntegrationFailureDisposition.AMBIGUOUS
    (outcome,) = cancelled.value.operation_detail.outcome_groups[0].outcomes
    assert outcome.status == "applied"


async def test_a_file_changed_after_approval_stops_everything(monkeypatch):
    graph = AdsGraph(live_ad_sets("8"))
    source = file_source()
    monkeypatch.setattr(preparation_module, "resolve_media_source", AsyncMock(return_value=source))
    file_image = FileReference(entity_id=source.file.id, label="spring.png")
    call = request(design("From File", media=file_image))
    stale = {**source.approval_details(), "revision_id": str(uuid4())}

    entry, _audit = await run_tool(monkeypatch, graph, call, reviewed={"_files": [stale]})

    assert entry["error_code"] == "source_changed"
    assert graph.creates == [] and graph.dry_run_names == []


async def test_a_file_that_is_unavailable_to_the_workspace_is_refused(monkeypatch):
    graph = AdsGraph(live_ad_sets("8"))

    async def not_here(_db, *, workspace_id, file_id):
        raise NotFoundError("File not found")

    monkeypatch.setattr(
        "integrations.meta_ads.operations.media_source.resolve_workspace_file_source", not_here
    )
    file_image = FileReference(entity_id=uuid4(), label="theirs.png")

    entry, _audit = await run_tool(
        monkeypatch, graph, request(design(media=file_image)), proposed=request()
    )

    assert entry["error_code"] == "source_unavailable"
    assert graph.creates == [] and graph.dry_run_names == []
