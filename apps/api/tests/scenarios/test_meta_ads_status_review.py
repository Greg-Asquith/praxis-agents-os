"""Edited Meta status approvals need a retained review before only the reviewed objects change."""

from dataclasses import replace
from unittest.mock import AsyncMock

import httpx2
import pytest
from sqlalchemy import select

from core.exceptions.general import AppValidationError
from integrations.meta_ads import throttle
from integrations.meta_ads.client import MetaAdsClient
from integrations.meta_ads.references import MetaAdsAdReference, MetaAdsCampaignReference
from integrations.meta_ads.tools.update_status import DEFINITION
from models.agent_run import AgentRun
from models.user import User
from models.workspace import Workspace, WorkspaceMembership
from services.agent_runs.review_approval import review_agent_run_approval
from services.agent_runs.schemas import AgentRunReviewApprovalRequest
from services.agents.runtime.approval_projection import build_approval_graph, project_approval_graph
from services.agents.runtime.approval_state import load_suspended_run_state
from services.agents.runtime.tools.registry import RUNTIME_TOOL_CATALOG
from services.integrations.context.domain import ResolvedActiveContext
from tests.integrations.meta_ads.support import FakeGraph, context_entry, obj, static_token
from tests.support.approvals import ScenarioDecision
from tests.support.delegation import resume_scenario
from tests.support.scenario import (
    ToolCall,
    ToolTurn,
    build_scenario_agent,
    run_scenario,
    scripted_model,
)

CAMPAIGN = MetaAdsCampaignReference(account_id="123", campaign_id="9", label="Spring")
AD = MetaAdsAdReference(account_id="123", campaign_id="9", adset_id="8", ad_id="7", label="Ad")


async def _review(session_factory, context, override_args):
    async with session_factory() as db:
        root = await db.get(AgentRun, context.run_id)
        projection = project_approval_graph(build_approval_graph(root, {root.id: root}))
        actor = await db.get(User, context.user_id)
        membership = await db.scalar(
            select(WorkspaceMembership).where(
                WorkspaceMembership.workspace_id == context.workspace_id,
                WorkspaceMembership.user_id == context.user_id,
            )
        )
        await review_agent_run_approval(
            db,
            actor=actor,
            workspace=await db.get(Workspace, context.workspace_id),
            membership=membership,
            run_id=root.id,
            payload=AgentRunReviewApprovalRequest(
                approval_id=projection.approvals[0].approval_id,
                approval_revision=projection.approval_revision,
                override_args=override_args,
            ),
        )


async def test_edited_selection_runs_only_after_review(db_session_factory, monkeypatch):
    monkeypatch.setitem(
        RUNTIME_TOOL_CATALOG, DEFINITION.name, replace(DEFINITION, availability_check=lambda: True)
    )
    entry = replace(context_entry("123"), write_allowed=True)
    active = AsyncMock(return_value=ResolvedActiveContext(entries=(entry,)))
    monkeypatch.setattr("services.agents.runtime.execute.setup.resolve_active_context", active)
    monkeypatch.setattr(
        "services.agents.runtime.entity_references.service.resolve_active_context", active
    )
    monkeypatch.setattr(
        "services.audit_events.integration_events.get_async_db_session_factory",
        lambda: db_session_factory,
    )
    monkeypatch.setattr(throttle, "_accounts", {})
    graph = FakeGraph(
        [
            obj("9", "campaign", status="ACTIVE"),
            obj("8", "adset", campaign_id="9", status="ACTIVE"),
            obj("7", "ad", campaign_id="9", adset_id="8", status="ACTIVE"),
        ]
    )
    http = httpx2.AsyncClient(transport=httpx2.MockTransport(graph.handle))
    client = AsyncMock(return_value=MetaAdsClient(static_token, client=http))
    for target in (
        "integrations.meta_ads.entity_resolvers.utils.meta_ads_client_for_principal",
        "integrations.meta_ads.tools.update_status.meta_ads_client_for_principal",
        "integrations.meta_ads.tools.update_status.meta_ads_client",
    ):
        monkeypatch.setattr(target, client)

    context = await build_scenario_agent(db_session_factory, tool_names=[DEFINITION.name])
    proposed = {"status": "PAUSED", "campaigns": [CAMPAIGN.model_dump(mode="json")]}
    model = scripted_model(
        turns=[ToolTurn((ToolCall(DEFINITION.name, proposed, "status"),)), "Done."]
    )
    # The operator drops the campaign family and adds an ad the agent didn't propose.
    edited = {"status": "PAUSED", "campaigns": None, "ads": [AD.model_dump(mode="json")]}
    decision = ScenarioDecision(tool_call_id="status", decision="approved", override_args=edited)

    async with http:
        suspended = await run_scenario(db_session_factory, context, model=model)
        assert suspended.run.status == "awaiting_approval"

        with pytest.raises(AppValidationError) as unreviewed:
            await resume_scenario(db_session_factory, context, model=model, decisions=[decision])
        assert unreviewed.value.details["error_code"] == "approval_review_required"
        with pytest.raises(AppValidationError):
            await _review(db_session_factory, context, edited | {"ads": None})
        assert graph.posts == []

        await _review(db_session_factory, context, edited)
        async with db_session_factory() as db:
            retained = load_suspended_run_state(await db.get(AgentRun, context.run_id))
        reviewed = retained.deferred_tool_requests.metadata["status"]["display_args"]
        assert reviewed["_reviewed_selection"] == {"status": "PAUSED", "objects": ["ad:7"]}

        completed = await resume_scenario(
            db_session_factory, context, model=model, decisions=[decision]
        )

    assert completed.run.status == "completed"
    assert graph.posts == ["7"]
    assert graph.objects["9"]["status"] == "ACTIVE"
    operations = [
        row
        for row in completed.audit_rows
        if row.details.get("provider_operation") == "update_status"
    ]
    pending, terminal = sorted(operations, key=lambda row: row.status != "pending")
    assert (pending.status, terminal.status) == ("pending", "success")
    assert terminal.details["related_event_id"] == str(pending.id)
