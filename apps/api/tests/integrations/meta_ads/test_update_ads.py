# apps/api/tests/integrations/meta_ads/test_update_ads.py

"""Ad edits: names and ad-level schedules, Meta's rules before approval, and read-back proof."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock
from urllib.parse import parse_qsl
from uuid import uuid4
from zoneinfo import ZoneInfo

import httpx2
import pytest
from pydantic_ai import ModelRetry

from integrations.meta_ads.client import MetaAdsClient
from integrations.meta_ads.operations.edit_ad import edit_problems
from integrations.meta_ads.references import MetaAdsAdReference
from integrations.meta_ads.tools import update_ads as tool_module
from integrations.meta_ads.tools.schemas.ad_edits import MetaAdsAdEdit, MetaAdsUpdateAdsOutput
from integrations.meta_ads.tools.schemas.objects import MetaAdsObject
from services.integrations.context.domain import ResolvedActiveContext
from tests.integrations.meta_ads.support import FakeGraph, context_entry, obj, static_token

ZONE = ZoneInfo("Europe/Paris")
NOW = datetime.now(UTC)
# Sunday night next week, in the account's time zone.
SUNDAY = (NOW.astimezone(ZONE) + timedelta(days=13 - NOW.astimezone(ZONE).weekday())).replace(
    hour=23, minute=59, second=0, microsecond=0
)
_TIMES = {"ad_schedule_start_time", "ad_schedule_end_time"}


class AdGraph(FakeGraph):
    """Applies posted names and ad times the way Meta stores them; empty removes a time."""

    def handle_post(self, request, object_id):
        response = super().handle_post(request, object_id)
        form = dict(parse_qsl(request.content.decode(), keep_blank_values=True))
        if "execution_options" not in form and self.post.get(object_id, "apply") == "apply":
            item = self.objects[object_id]
            for key, value in form.items():
                if key in _TIMES and value == "":
                    item.pop(key, None)
                elif key == "name" or key in _TIMES:
                    item[key] = value
        return response


def _graph(**ad_fields) -> AdGraph:
    sale = {"objective": "OUTCOME_SALES"}
    return AdGraph(
        [
            obj("9", "campaign", status="ACTIVE"),
            obj("5", "campaign", status="ACTIVE"),
            obj("8", "adset", campaign_id="9", status="ACTIVE", campaign=sale),
            obj("6", "adset", campaign_id="5", status="ACTIVE", campaign={"objective": "x"}),
            obj("1", "ad", campaign_id="9", adset_id="8", status="ACTIVE", **ad_fields),
            obj("2", "ad", campaign_id="9", adset_id="8", status="ACTIVE"),
            obj("3", "ad", campaign_id="5", adset_id="6", status="ACTIVE"),
        ]
    )


def _edit(ad_id: str, account_id: str = "123", **settings) -> MetaAdsAdEdit:
    reference = MetaAdsAdReference(
        account_id=account_id, campaign_id="9", adset_id="8", ad_id=ad_id, label=f"Ad {ad_id}"
    )
    return MetaAdsAdEdit(ad=reference, **settings)


def _shown(graph: AdGraph, *ids: str) -> dict:
    """What the approval card showed: each ad's settings as they were when proposed."""
    return {
        ad_id: {
            "before": {
                "name": graph.objects[ad_id]["name"],
                "start_at": None,
                "end_at": None,
            }
        }
        for ad_id in ids
    }


def _context(monkeypatch, http, edits, checks):
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
    return SimpleNamespace(
        deps=SimpleNamespace(
            active_context=ResolvedActiveContext(entries=(entry,)),
            workspace=SimpleNamespace(id=uuid4()),
            agent=SimpleNamespace(id=uuid4(), name="Ads agent"),
            run=SimpleNamespace(id=uuid4(), user_id=uuid4()),
        ),
        tool_name="meta_ads_update_ads",
        tool_call_id="call-meta-ads",
    ), audit


async def test_one_approval_renames_ads_and_ends_a_sale_ad_on_sunday_night(monkeypatch):
    graph = _graph()
    sunday = SUNDAY.strftime("%Y-%m-%dT%H:%M")
    edits = [
        _edit("1", name="UK | Sale | Video", end_at=sunday),
        _edit("2", name="UK | Sale | Image"),
    ]
    http = httpx2.AsyncClient(transport=httpx2.MockTransport(graph.handle))
    ctx, audit = _context(monkeypatch, http, edits, _shown(graph, "1", "2"))

    async with http:
        result = await tool_module.meta_ads_update_ads(ctx, changes=edits)

    MetaAdsUpdateAdsOutput.model_validate(result)
    assert graph.dry_runs == ["1", "2"] and graph.posts == ["1", "2"]
    assert graph.sent[0]["ad_schedule_end_time"] == SUNDAY.isoformat()
    rows = result["results"][0]["data"]["ads"]
    assert [row["outcome"] for row in rows] == ["updated", "updated"]
    assert rows[0]["changes"][1] == {
        "setting": "end_at",
        "before": None,
        "requested": sunday,
        "after": sunday,
    }
    pending = audit.await_args_list[0].kwargs["operation_detail"].intent_groups[0].items[0]
    assert pending.fields["requested"] == {"name": "UK | Sale | Video", "end_at": sunday}


async def test_none_removes_the_ads_own_end_time(monkeypatch):
    graph = _graph(ad_schedule_end_time=SUNDAY.isoformat())
    edits = [_edit("1", end_at="none")]
    shown = {"1": {"before": {"end_at": SUNDAY.strftime("%Y-%m-%dT%H:%M")}}}
    http = httpx2.AsyncClient(transport=httpx2.MockTransport(graph.handle))
    ctx, _audit = _context(monkeypatch, http, edits, shown)

    async with http:
        result = await tool_module.meta_ads_update_ads(ctx, changes=edits)

    # AdGraph drops the time only when Meta receives it empty.
    assert "ad_schedule_end_time" not in graph.objects["1"]
    assert result["results"][0]["data"]["ads"][0]["outcome"] == "updated"


async def test_an_ad_that_changed_after_approval_is_not_sent(monkeypatch):
    graph = _graph()
    edits = [_edit("1", name="New name")]
    shown = {"1": {"before": {"name": "An older name"}}}
    http = httpx2.AsyncClient(transport=httpx2.MockTransport(graph.handle))
    ctx, _audit = _context(monkeypatch, http, edits, shown)

    async with http:
        result = await tool_module.meta_ads_update_ads(ctx, changes=edits)

    assert graph.posts == []
    assert result["results"][0]["data"]["ads"][0]["error_code"] == "CHANGED_SINCE_APPROVAL"


async def test_an_ad_outside_the_selected_ad_accounts_is_refused(monkeypatch):
    graph = _graph()
    edits = [_edit("1", account_id="999", name="Elsewhere")]
    http = httpx2.AsyncClient(transport=httpx2.MockTransport(graph.handle))
    ctx, _audit = _context(monkeypatch, http, edits, _shown(graph, "1"))

    async with http:
        with pytest.raises(ModelRetry, match="no longer in the active integration context"):
            await tool_module.meta_ads_update_ads(ctx, changes=edits)

    assert graph.posts == [] and graph.dry_runs == []


async def test_an_ad_schedule_outside_a_sales_campaign_is_refused_before_anything_is_sent(
    monkeypatch,
):
    graph = _graph()
    edits = [_edit("3", end_at=SUNDAY.strftime("%Y-%m-%dT%H:%M"))]
    http = httpx2.AsyncClient(transport=httpx2.MockTransport(graph.handle))
    ctx, _audit = _context(monkeypatch, http, edits, _shown(graph, "3"))

    async with http:
        result = await tool_module.meta_ads_update_ads(ctx, changes=edits)

    entry = result["results"][0]
    assert graph.posts == [] and graph.dry_runs == []
    assert entry["status"] == "error" and "sales and app promotion" in entry["error_message"]


def _object(object_id: str, **fields) -> MetaAdsObject:
    values = {
        key: None
        for key in MetaAdsObject.model_fields
        if key not in ("id", "destination_type", "promoted_object")
    }
    return MetaAdsObject(**{**values, "id": object_id, **fields})


def test_an_archived_ad_can_be_renamed_but_not_rescheduled():
    ad = _object("1", status="ARCHIVED")
    ad_set = _object("8", objective="OUTCOME_SALES")
    later = (NOW + timedelta(days=2)).astimezone(ZONE).strftime("%Y-%m-%dT%H:%M")

    assert edit_problems(_edit("1", name="Old sale"), ad, ad_set, zone=ZONE, now=NOW) == []
    assert edit_problems(_edit("1", end_at=later), ad, ad_set, zone=ZONE, now=NOW) == [
        "This ad is archived or deleted, so only its name can change."
    ]


def test_an_end_time_after_the_ad_set_ends_is_refused():
    ad_set_end = NOW + timedelta(days=3)
    ad_set = _object("8", objective="OUTCOME_SALES", end_time=ad_set_end.isoformat())
    late = (NOW + timedelta(days=5)).astimezone(ZONE).strftime("%Y-%m-%dT%H:%M")

    problems = edit_problems(
        _edit("1", end_at=late), _object("1", status="ACTIVE"), ad_set, zone=ZONE, now=NOW
    )

    assert len(problems) == 1 and "when the ad set ends" in problems[0]
