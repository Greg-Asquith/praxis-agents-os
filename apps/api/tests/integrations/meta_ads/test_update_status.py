"""Meta status changes: no retry after sending, read-back proof, and scoped references."""

import asyncio
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import httpx2
import pytest

from core.exceptions.general import AppValidationError
from integrations.meta_ads.client import MetaAdsClient
from integrations.meta_ads.entity_resolvers.utils import resolve_objects, search_objects
from integrations.meta_ads.models import MetaAdsObjectBudget
from integrations.meta_ads.operations.mutations import (
    MetaAdsMutationEffect,
    MetaAdsMutationLedger,
    MetaAdsMutationParent,
)
from integrations.meta_ads.operations.update_status import read_status_targets, update_status
from integrations.meta_ads.references import MetaAdsAdReference, MetaAdsCampaignReference
from integrations.meta_ads.tools.schemas.status import MetaAdsStatusOutput
from integrations.meta_ads.tools.update_status import (
    _account_delivery,
    _child_budgets,
    _result,
    meta_ads_update_status,
)
from integrations.meta_ads.tools.utils.mutation_evidence import (
    audit_status,
    terminal_operation_detail,
)
from services.agent_runs.utils import validate_retained_review
from services.audit_events import (
    AuditStatus,
    IntegrationOperationIntent,
    IntegrationOperationIntentGroup,
    IntegrationOperationTarget,
    PendingIntegrationOperationDetail,
)
from services.integrations.context.domain import ResolvedActiveContext
from tests.integrations.meta_ads.support import FakeGraph, context_entry, obj, static_token


async def run(graph: FakeGraph, ids, status="ACTIVE"):
    async with httpx2.AsyncClient(transport=httpx2.MockTransport(graph.handle)) as http:
        client = MetaAdsClient(static_token, client=http)
        targets, missing = await read_status_targets(
            client, account_id="123", currency="EUR", object_ids=ids
        )
        assert missing == []
        ledger, refreshed = await update_status(
            client, account_id="123", currency="EUR", targets=targets, status=status
        )
    return {dict(parent.identity)["object_id"]: parent for parent in ledger.parents}, refreshed


async def test_ambiguous_change_is_not_retried_and_ends_unverified(monkeypatch):
    sleep = AsyncMock()
    monkeypatch.setattr("services.integrations.http.asyncio.sleep", sleep)
    graph = FakeGraph(
        [obj("1", "campaign"), obj("2", "campaign")],
        post={"1": "timeout"},
    )

    parents, _refreshed = await run(graph, {"campaign": ["1", "2"]})

    assert graph.posts == ["1", "2"]
    sleep.assert_not_awaited()
    assert parents["1"].outcome == "unverified"
    assert parents["2"].outcome == "applied"
    assert dict(parents["2"].effects[0].fields)["status"] == "ACTIVE"


async def test_throttle_rejection_is_failed_not_unverified():
    graph = FakeGraph(
        [obj("1", "campaign"), obj("2", "campaign")],
        post={"1": "throttle"},
    )

    parents, _refreshed = await run(graph, {"campaign": ["1", "2"]})

    assert graph.posts == ["1", "2"]
    assert parents["1"].outcome == "failed"
    assert parents["1"].effects[0].error_code == "IntegrationRateLimitError"
    assert parents["2"].outcome == "applied"


async def test_turning_on_sends_children_before_their_campaign():
    graph = FakeGraph(
        [
            obj("9", "campaign"),
            obj("8", "adset", campaign_id="9"),
            obj("7", "ad", campaign_id="9", adset_id="8"),
        ]
    )

    await run(graph, {"campaign": ["9"], "adset": ["8"], "ad": ["7"]})

    assert graph.posts == ["7", "8", "9"]


async def test_cancellation_keeps_sent_change_unverified_and_later_changes_unsent():
    graph = FakeGraph(
        [obj("1", "campaign", status="ACTIVE"), obj("2", "campaign", status="ACTIVE")]
    )

    def cancel_first(request):
        if request.method == "POST":
            graph.posts.append("1")
            raise asyncio.CancelledError
        return graph.handle(request)

    async with httpx2.AsyncClient(transport=httpx2.MockTransport(cancel_first)) as http:
        client = MetaAdsClient(static_token, client=http)
        targets, _missing = await read_status_targets(
            client, account_id="123", currency="EUR", object_ids={"campaign": ["1", "2"]}
        )
        with pytest.raises(asyncio.CancelledError) as cancelled:
            await update_status(
                client, account_id="123", currency="EUR", targets=targets, status="PAUSED"
            )

    outcomes = [parent.outcome for parent in cancelled.value.ledger.parents]
    assert graph.posts == ["1"]
    assert outcomes == ["unverified", "failed"]


async def test_read_back_that_disagrees_marks_the_row_and_set_objects_are_skipped():
    graph = FakeGraph(
        [
            obj("1", "adset", campaign_id="9"),
            obj("2", "adset", campaign_id="9", status="ACTIVE"),
            obj("9", "campaign", status="ACTIVE"),
        ],
        post={"1": "accept_without_change"},
    )

    async with httpx2.AsyncClient(transport=httpx2.MockTransport(graph.handle)) as http:
        client = MetaAdsClient(static_token, client=http)
        targets, _missing = await read_status_targets(
            client, account_id="123", currency="EUR", object_ids={"adset": ["1", "2"]}
        )
        ledger, refreshed = await update_status(
            client, account_id="123", currency="EUR", targets=targets, status="ACTIVE"
        )

    assert graph.posts == ["1"]
    disagreed, already_on = ledger.parents
    assert disagreed.outcome == "unverified"
    assert disagreed.effects[0].error_code == "STATUS_NOT_CONFIRMED"
    assert already_on.outcome == "skipped"
    assert ledger.external_refs == ()
    # The state Meta returned stays visible instead of reading like a failed read.
    row = _result("123", targets, ledger, refreshed, "ACTIVE")["objects"][0]
    assert (row["outcome"], row["status"], row["effective_status"]) == (
        "unverified",
        "PAUSED",
        "PAUSED",
    )


async def test_turning_on_projects_the_whole_selection():
    graph = FakeGraph(
        [
            obj("9", "campaign"),
            obj("8", "adset", campaign_id="9", status="ACTIVE", effective_status="CAMPAIGN_PAUSED")
            | {"daily_budget": "1500"},
            # Paused now, but turned on in the same change.
            obj("7", "adset", campaign_id="9") | {"daily_budget": "2500"},
            obj("3", "adset", campaign_id="9"),
            obj("6", "adset", campaign_id="5"),
            obj("5", "campaign", status="ACTIVE"),
            obj("4", "ad", campaign_id="5", adset_id="6"),
            obj("2", "adset", campaign_id="1"),
            obj("1", "campaign"),
        ]
    )
    async with httpx2.AsyncClient(transport=httpx2.MockTransport(graph.handle)) as http:
        preview = await _account_delivery(
            MetaAdsClient(static_token, client=http),
            "123",
            "EUR",
            {"campaign": ["9", "5"], "adset": ["7", "2"], "ad": ["4"]},
        )

    assert preview["4"]["blocked_by"] == ["ad_set"]
    assert preview["9"]["starting_children"] == 2
    assert preview["9"]["daily_budget"] == "40"
    assert preview["5"] == {"blocked_by": [], "already_on": True}
    assert preview["2"] == {"blocked_by": ["campaign"]}


def test_object_with_one_applied_effect_is_partial_not_failure():
    pending = PendingIntegrationOperationDetail(
        target=IntegrationOperationTarget(entity_type="meta_ads_ad_account", external_id="123"),
        intent_groups=[
            IntegrationOperationIntentGroup(
                key="ads:create",
                action="create",
                entity_type="meta_ads_ad",
                items=[IntegrationOperationIntent(fields={"object_id": "1"})],
            )
        ],
    )
    parent = MetaAdsMutationParent(
        identity=(("object_id", "1"),),
        decision="submit",
        effects=(
            MetaAdsMutationEffect(
                fields=(("step", "upload"),), outcome="applied", external_ref="9"
            ),
            MetaAdsMutationEffect(
                fields=(("step", "create"),), outcome="failed", error_code="E", message="No."
            ),
        ),
    )
    ledger = MetaAdsMutationLedger(action="create", parents=(parent,))

    detail = terminal_operation_detail(pending, ledger, identity_key="object_id")

    assert (detail.intent_counts.failed, detail.effect_counts.applied) == (1, 1)
    assert audit_status(detail) is AuditStatus.PARTIAL


def test_ad_set_budget_totals_keep_every_digit():
    large = "9" * 40
    adsets = [
        SimpleNamespace(budget=MetaAdsObjectBudget(kind="daily", amount=amount, remaining=None))
        for amount in (f"{large}.01", "0.99")
    ]

    assert _child_budgets(adsets)["daily_budget"] == f"1{'0' * 40}.00"


async def test_skipped_child_reports_its_delivery_after_its_parent_changes():
    graph = FakeGraph(
        [
            obj("9", "campaign"),
            obj("8", "adset", campaign_id="9", status="ACTIVE", effective_status="CAMPAIGN_PAUSED"),
        ]
    )

    parents, refreshed = await run(graph, {"campaign": ["9"], "adset": ["8"]})

    assert graph.posts == ["9"]
    assert parents["8"].outcome == "skipped" and parents["8"].effects == ()
    assert refreshed["8"].effective_status == "ACTIVE"


async def test_resolver_ignores_objects_in_accounts_outside_active_context(monkeypatch):
    lookup = AsyncMock(return_value=SimpleNamespace(objects=[]))
    monkeypatch.setattr("integrations.meta_ads.entity_resolvers.utils.list_objects", lookup)
    monkeypatch.setattr(
        "integrations.meta_ads.entity_resolvers.utils.meta_ads_client_for_principal", AsyncMock()
    )
    ctx = SimpleNamespace(
        active_context=ResolvedActiveContext(entries=(context_entry("123"),)),
        db=None,
        actor=None,
        workspace=None,
    )
    foreign = MetaAdsCampaignReference(account_id="999", campaign_id="1", label="Other client")

    choices = await resolve_objects(
        ctx,
        [foreign.model_dump(mode="json")],
        object_type="campaign",
        reference_type=MetaAdsCampaignReference,
        choice=lambda *_args: None,
    )

    assert choices == ()
    lookup.assert_not_awaited()


async def test_resolver_finds_no_object_the_allowed_account_does_not_list(monkeypatch):
    graph = FakeGraph([obj("5", "campaign")])
    paths: list[str] = []

    def handle(request):
        paths.append(request.url.path)
        return graph.handle(request)

    http = httpx2.AsyncClient(transport=httpx2.MockTransport(handle))

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
    # The account is allowed, but this campaign belongs to another account the token can read.
    stray = MetaAdsCampaignReference(account_id="123", campaign_id="1", label="Other client")

    async with http:
        choices = await resolve_objects(
            ctx,
            [stray.model_dump(mode="json")],
            object_type="campaign",
            reference_type=MetaAdsCampaignReference,
            choice=lambda _entry, item, _currency: item.id,
        )

    assert choices == ()
    assert paths and all(path.split("/")[2] == "act_123" for path in paths)


async def test_tool_records_live_before_state_and_unverified_outcome(monkeypatch):
    graph = FakeGraph(
        [
            obj("1", "ad", campaign_id="9", adset_id="8"),
            obj("8", "adset", campaign_id="9"),
            obj("9", "campaign", status="ACTIVE"),
        ],
        post={"1": "timeout"},
    )
    pending_event_id = uuid4()
    audit = AsyncMock(return_value=pending_event_id)
    monkeypatch.setattr(
        "services.integrations.operations.record_integration_operation_audit_event", audit
    )
    http = httpx2.AsyncClient(transport=httpx2.MockTransport(graph.handle))

    async def client(_ctx, _entry):
        return MetaAdsClient(static_token, client=http)

    monkeypatch.setattr("integrations.meta_ads.tools.update_status.meta_ads_client", client)
    entry = replace(context_entry("123"), write_allowed=True)
    ctx = SimpleNamespace(
        deps=SimpleNamespace(
            active_context=ResolvedActiveContext(entries=(entry,)),
            workspace=SimpleNamespace(id=uuid4()),
            agent=SimpleNamespace(id=uuid4(), name="Ads agent"),
            run=SimpleNamespace(id=uuid4(), user_id=uuid4()),
        ),
        tool_name="meta_ads_update_status",
        tool_call_id="call-meta-status",
    )
    reference = MetaAdsAdReference(
        account_id="123", campaign_id="9", adset_id="8", ad_id="1", label="Spring ad"
    )

    async with http:
        result = await meta_ads_update_status(ctx, status="ACTIVE", ads=[reference])

    MetaAdsStatusOutput.model_validate(result)
    entry_result = result["results"][0]
    assert entry_result["error_code"] == "unverified_mutation"
    assert entry_result["data"]["objects"][0]["outcome"] == "unverified"
    pending, terminal = (call.kwargs for call in audit.await_args_list)
    assert pending["operation_detail"].intent_groups[0].items[0].fields == {
        "object_id": "1",
        "object_name": "ad 1",
        "previous_status": "PAUSED",
        "previous_effective_status": "PAUSED",
        "campaign_status": "ACTIVE",
        "adset_status": "PAUSED",
    }
    assert terminal["status"] == "unverified"
    assert terminal["related_event_id"] == pending_event_id


def test_resume_requires_review_when_status_or_targets_change():
    campaign = MetaAdsCampaignReference(account_id="123", campaign_id="9", label="Spring")
    other = MetaAdsCampaignReference(account_id="123", campaign_id="8", label="Summer")
    reviewed = {"status": "PAUSED", "campaigns": [campaign.model_dump(mode="json")]}
    leaf = SimpleNamespace(
        call=SimpleNamespace(tool_name="meta_ads_update_status"),
        metadata={"display_args": reviewed | {"_delivery": {}}},
    )

    validate_retained_review(leaf, reviewed)
    for edited in (
        reviewed | {"status": "ACTIVE"},
        reviewed | {"campaigns": [other.model_dump(mode="json")]},
        reviewed | {"ads": []},
    ):
        with pytest.raises(AppValidationError) as caught:
            validate_retained_review(leaf, edited)
        assert caught.value.details["error_code"] == "approval_review_required"


async def test_search_across_accounts_never_shares_the_session_concurrently(monkeypatch):
    in_flight = 0
    overlapped = False

    async def credential_lookup(*_args, **_kwargs):
        nonlocal in_flight, overlapped
        in_flight += 1
        overlapped = overlapped or in_flight > 1
        await asyncio.sleep(0)
        in_flight -= 1
        return AsyncMock()

    module = "integrations.meta_ads.entity_resolvers.utils"
    monkeypatch.setattr(f"{module}.meta_ads_client_for_principal", credential_lookup)
    monkeypatch.setattr(
        f"{module}.list_objects", AsyncMock(return_value=SimpleNamespace(objects=[]))
    )
    ctx = SimpleNamespace(
        active_context=ResolvedActiveContext(entries=(context_entry("123"), context_entry("456"))),
        db=None,
        actor=None,
        workspace=None,
    )

    await search_objects(
        ctx, "Spring", object_type="campaign", page_size=10, cursor=None, choice=lambda *_: None
    )

    assert not overlapped
