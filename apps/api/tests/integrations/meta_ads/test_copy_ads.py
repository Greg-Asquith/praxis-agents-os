# apps/api/tests/integrations/meta_ads/test_copy_ads.py

"""Copying Meta ads: checks before anything is copied, one send per copy, and proof after."""

import json
from unittest.mock import AsyncMock
from urllib.parse import parse_qsl

import httpx2
import pytest
from pydantic_ai import ModelRetry

from integrations.meta_ads.operations import copy_ads as operation_module
from integrations.meta_ads.references import MetaAdsAdReference, MetaAdsAdSetReference
from integrations.meta_ads.tools.copy_ads import meta_ads_copy_ads
from integrations.meta_ads.tools.schemas.copies import MetaAdsAdCopy, MetaAdsCopyAdsOutput
from tests.integrations.meta_ads.support import (
    FakeGraph,
    obj,
    write_tool_context,
)

PRIMARY_TEXT = "Spring sale on now"


def creative(*, ai_generated: bool = False) -> dict:
    features = {"inline_comment": {"enroll_status": "OPT_OUT"}}
    if ai_generated:
        features["image_uncrop"] = {"enroll_status": "OPT_IN"}
    return {
        "id": "5500",
        "object_story_spec": {
            "page_id": "11",
            "link_data": {"message": PRIMARY_TEXT, "image_hash": "abc", "link": "https://x.test"},
        },
        "degrees_of_freedom_spec": {"creative_features_spec": features},
    }


def source(ad_id: str = "500", name: str = "Winner", **values) -> dict:
    return obj(ad_id, "ad", adset_id="8", campaign_id="9", name=name, creative=creative(**values))


def live_ad_sets(*adset_ids: str, **values) -> list[dict]:
    return [obj(adset_id, "adset", campaign_id="9", **values) for adset_id in adset_ids]


def copy(ad_id: str = "500", adset_id: str = "7", *, account_id: str = "123", **values):
    return MetaAdsAdCopy(
        ad=MetaAdsAdReference(
            account_id="123", campaign_id="9", adset_id="8", ad_id=ad_id, label=f"ad {ad_id}"
        ),
        ad_set=MetaAdsAdSetReference(
            account_id=account_id, campaign_id="9", adset_id=adset_id, label=f"adset {adset_id}"
        ),
        **values,
    )


class CopyGraph(FakeGraph):
    """Copies ads through `/{ad_id}/copies` and renames them through `/{ad_id}`."""

    def __init__(self, objects, *, behaviour=None):
        super().__init__(objects)
        self.behaviour = behaviour or {}
        self.copies: list[dict[str, str]] = []
        self.renames: list[dict[str, str]] = []
        self.next_id = 900

    def handle(self, request: httpx2.Request) -> httpx2.Response:
        path = request.url.path.split("/")[2:]
        if request.method != "POST":
            return super().handle(request)
        form = dict(parse_qsl(request.content.decode()))
        if path[1:] == ["copies"]:
            return self.copy(request, path[0], form)
        self.renames.append({"ad_id": path[0], **form})
        self.objects[path[0]]["name"] = form["name"]
        return httpx2.Response(200, json={"success": True}, request=request)

    def copy(self, request: httpx2.Request, ad_id: str, form: dict) -> httpx2.Response:
        self.copies.append({"ad_id": ad_id, **form})
        behaviour = self.behaviour.get((ad_id, form["adset_id"]), "apply")
        if behaviour == "reject":
            error = {"code": 100, "error_user_msg": "Ad set is full.", "fbtrace_id": "t"}
            return httpx2.Response(400, json={"error": error}, request=request)
        copied_id = str(self.next_id)
        self.next_id += 1
        self.objects[copied_id] = {
            **self.objects[ad_id],
            "id": copied_id,
            "adset_id": form["adset_id"],
            "status": form["status_option"],
            "effective_status": "PENDING_REVIEW",
            "created_time": "2099-01-01T00:00:00+0000",
        }
        if behaviour == "lose_reply":
            raise httpx2.ReadTimeout("lost", request=request)
        return httpx2.Response(200, json={"copied_ad_id": copied_id}, request=request)


async def run_tool(monkeypatch, graph: CopyGraph, copies: list[MetaAdsAdCopy], proposed=None):
    http = httpx2.AsyncClient(transport=httpx2.MockTransport(graph.handle))
    ctx, audit = write_tool_context(
        monkeypatch,
        http,
        tool_name="meta_ads_copy_ads",
        proposed={"copies": [item.model_dump(mode="json") for item in proposed or copies]},
    )
    async with http:
        result = await meta_ads_copy_ads(ctx, copies)
    MetaAdsCopyAdsOutput.model_validate(result)
    return result["results"][0], audit


async def test_a_copy_is_sent_paused_once_and_read_back_with_text_free_evidence(monkeypatch):
    graph = CopyGraph([source(), *live_ad_sets("8", "7")])

    entry, audit = await run_tool(monkeypatch, graph, [copy()])

    (sent,) = graph.copies
    assert (sent["adset_id"], sent["status_option"]) == ("7", "PAUSED")
    assert json.loads(sent["rename_options"]) == {"rename_strategy": "NO_RENAME"}
    (row,) = entry["data"]["copies"]
    assert (row["outcome"], row["name"], row["review"]) == ("copied", "Winner", "in_review")
    assert graph.renames == []
    pending, terminal = audit.await_args_list[0].kwargs, audit.await_args_list[-1].kwargs
    assert pending["operation_detail"].intent_groups[0].items[0].fields["source_ad_id"] == "500"
    # Evidence names the source, target, and status; it never holds the ad's text.
    for record in (pending, terminal):
        assert PRIMARY_TEXT not in json.dumps(record["operation_detail"].model_dump(mode="json"))
    assert terminal["status"] == "success"


async def test_a_lost_copy_reply_is_settled_by_name_and_never_resent(monkeypatch):
    graph = CopyGraph([source(), *live_ad_sets("8", "7")], behaviour={("500", "7"): "lose_reply"})

    entry, _audit = await run_tool(monkeypatch, graph, [copy()])

    (row,) = entry["data"]["copies"]
    assert len(graph.copies) == 1
    assert (row["outcome"], row["recovered"], row["ad_id"]) == ("copied", True, "900")


async def test_a_new_name_is_set_after_the_copys_id_is_checkpointed(monkeypatch):
    graph = CopyGraph([source(), *live_ad_sets("8", "7")])

    entry, audit = await run_tool(monkeypatch, graph, [copy(name="Winner | Lookalike")])

    assert graph.renames == [{"ad_id": "900", "name": "Winner | Lookalike"}]
    # The checkpoint is its own record, between the pending and terminal ones.
    checkpoint = audit.await_args_list[1].kwargs
    assert checkpoint["status"] == "pending"
    assert checkpoint["checkpoints"][0].references == {"ad_id": "900"}
    assert entry["data"]["copies"][0]["name"] == "Winner | Lookalike"


async def test_a_checkpoint_that_cant_be_recorded_stops_the_rename(monkeypatch):
    graph = CopyGraph([source(), *live_ad_sets("8", "7")])
    monkeypatch.setattr(
        operation_module,
        "checkpoint_integration_operation",
        AsyncMock(side_effect=RuntimeError("audit store down")),
    )

    entry, audit = await run_tool(monkeypatch, graph, [copy(name="Winner | Lookalike")])

    assert entry["status"] == "error"
    assert graph.renames == []
    terminal = audit.await_args_list[-1].kwargs
    assert terminal["status"] == "unverified"
    (outcome,) = terminal["operation_detail"].outcome_groups[0].outcomes
    # The copy exists; its rename was never sent.
    assert [effect.status for effect in outcome.effects] == ["applied", "failed"]


async def test_later_copies_continue_after_one_fails(monkeypatch):
    graph = CopyGraph([source(), *live_ad_sets("8", "7", "6")], behaviour={("500", "7"): "reject"})

    entry, audit = await run_tool(monkeypatch, graph, [copy(adset_id="7"), copy(adset_id="6")])

    assert [row["outcome"] for row in entry["data"]["copies"]] == ["failed", "copied"]
    assert audit.await_args_list[-1].kwargs["status"] == "partial"


async def test_a_source_with_an_ai_generated_change_is_copied_paused(monkeypatch):
    graph = CopyGraph([source(ai_generated=True), *live_ad_sets("8", "7")])

    entry, _audit = await run_tool(monkeypatch, graph, [copy(status="active")])

    assert graph.copies[0]["status_option"] == "PAUSED"
    (row,) = entry["data"]["copies"]
    assert (row["requested_status"], row["paused_for_ai"]) == ("paused", True)


async def test_a_target_ad_set_at_fifty_ads_refuses_every_copy(monkeypatch):
    existing = [obj(str(100 + index), "ad", adset_id="7", campaign_id="9") for index in range(50)]
    graph = CopyGraph([source(), *live_ad_sets("8", "7", "6"), *existing])

    entry, _audit = await run_tool(monkeypatch, graph, [copy(adset_id="6"), copy(adset_id="7")])

    assert entry["status"] == "error"
    assert "50 ads per ad set" in entry["error_message"]
    assert graph.copies == []


async def test_a_name_already_in_the_target_ad_set_refuses_the_copy(monkeypatch):
    # A lost reply is found by the source's name, so it must be free in the target.
    clash = obj("101", "ad", adset_id="7", campaign_id="9", name="Winner")
    graph = CopyGraph([source(), clash, *live_ad_sets("8", "7")])

    entry, _audit = await run_tool(monkeypatch, graph, [copy(name="Winner | New")])

    assert entry["status"] == "error"
    assert "already in" in entry["error_message"]
    assert graph.copies == []


async def test_a_copy_into_another_accounts_ad_set_is_refused(monkeypatch):
    graph = CopyGraph([source(), *live_ad_sets("8", "7")])

    with pytest.raises(ModelRetry, match="one ad account"):
        await run_tool(monkeypatch, graph, [copy(account_id="456")])

    assert graph.copies == []


async def test_a_target_ad_set_changed_on_the_card_is_re_read_and_used(monkeypatch):
    graph = CopyGraph([source(), *live_ad_sets("8", "7", "6")])

    entry, _audit = await run_tool(
        monkeypatch, graph, [copy(adset_id="6")], proposed=[copy(adset_id="7")]
    )

    assert entry["data"]["copies"][0]["outcome"] == "copied"
    assert [sent["adset_id"] for sent in graph.copies] == ["6"]


async def test_a_target_missing_from_the_account_is_refused_after_a_card_edit(monkeypatch):
    graph = CopyGraph([source(), *live_ad_sets("8", "7")])

    entry, _audit = await run_tool(
        monkeypatch, graph, [copy(adset_id="6")], proposed=[copy(adset_id="7")]
    )

    assert entry["status"] == "error"
    assert graph.copies == []


async def test_a_copy_of_an_ad_the_agent_did_not_propose_is_refused(monkeypatch):
    graph = CopyGraph([source(), source("501", "Other"), *live_ad_sets("8", "7")])

    entry, _audit = await run_tool(
        monkeypatch, graph, [copy("500"), copy("501")], proposed=[copy("500")]
    )

    assert entry["status"] == "error"
    assert graph.copies == []
