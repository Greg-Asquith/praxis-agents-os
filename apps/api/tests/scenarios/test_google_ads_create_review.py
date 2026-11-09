# apps/api/tests/scenarios/test_google_ads_create_review.py

"""Edited Google Ads creates need Google's answer on the card before they can be approved."""

from copy import deepcopy
from dataclasses import replace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select

from core.exceptions.general import AppValidationError
from integrations.google_ads.tools import create_ads as tool_module
from integrations.google_ads.tools.create_ads import DEFINITION
from models.agent_run import AgentRun
from models.user import User
from models.workspace import Workspace, WorkspaceMembership
from services.agent_runs.review_approval import review_agent_run_approval
from services.agent_runs.schemas import AgentRunReviewApprovalRequest
from services.agents.runtime.approval_projection import build_approval_graph, project_approval_graph
from services.agents.runtime.approval_state import load_suspended_run_state
from services.agents.runtime.tools.registry import RUNTIME_TOOL_CATALOG
from services.integrations.context.domain import ResolvedActiveContext
from tests.integrations.google_ads.test_create_ads_tool import _C, _Account, _ad, _entry
from tests.support.approvals import ScenarioDecision
from tests.support.delegation import resume_scenario
from tests.support.scenario import (
    ToolCall,
    ToolTurn,
    build_scenario_agent,
    run_scenario,
    scripted_model,
)


async def _review(session_factory, context, override_args):
    """Runs the operator's Check Changes and returns the checks it retained."""
    async with session_factory() as db:
        root = await db.get(AgentRun, context.run_id)
        projection = project_approval_graph(build_approval_graph(root, {root.id: root}))
        membership = await db.scalar(
            select(WorkspaceMembership).where(
                WorkspaceMembership.workspace_id == context.workspace_id,
                WorkspaceMembership.user_id == context.user_id,
            )
        )
        await review_agent_run_approval(
            db,
            actor=await db.get(User, context.user_id),
            workspace=await db.get(Workspace, context.workspace_id),
            membership=membership,
            run_id=root.id,
            payload=AgentRunReviewApprovalRequest(
                approval_id=projection.approvals[0].approval_id,
                approval_revision=projection.approval_revision,
                override_args=override_args,
            ),
        )
    async with session_factory() as db:
        state = load_suspended_run_state(await db.get(AgentRun, context.run_id))
    return state.deferred_tool_requests.metadata["create"]["display_args"]["_checks"]


async def test_an_edited_ad_gets_googles_answer_and_runs_only_as_checked(
    db_session_factory, monkeypatch
):
    monkeypatch.setitem(
        RUNTIME_TOOL_CATALOG, DEFINITION.name, replace(DEFINITION, availability_check=lambda: True)
    )
    active = AsyncMock(return_value=ResolvedActiveContext(entries=(_entry(),)))
    monkeypatch.setattr("services.agents.runtime.execute.setup.resolve_active_context", active)
    monkeypatch.setattr(
        "services.agents.runtime.entity_references.service.resolve_active_context", active
    )
    monkeypatch.setattr(
        "services.audit_events.integration_events.get_async_db_session_factory",
        lambda: db_session_factory,
    )
    account = _Account(
        channels={"20": "SEARCH", "22": "SEARCH"},
        rejected={f"{_C}/adGroups/22": "DESTINATION_NOT_WORKING"},
    )
    client = AsyncMock(return_value=account)
    monkeypatch.setattr(tool_module, "google_ads_client_for_principal", client)
    monkeypatch.setattr(tool_module, "google_ads_client", client)

    context = await build_scenario_agent(db_session_factory, tool_names=[DEFINITION.name])
    proposed = {"ads": [_ad("20")], "status": "PAUSED"}
    model = scripted_model(
        turns=[ToolTurn((ToolCall(DEFINITION.name, proposed, "create"),)), "Done."]
    )
    rejected = {"ads": [_ad("22", headline="Trail Runners")], "status": "PAUSED"}
    fixed = {"ads": [_ad("20", headline="Trail Runners")], "status": "PAUSED"}

    suspended = await run_scenario(db_session_factory, context, model=model)
    assert suspended.run.status == "awaiting_approval"

    with pytest.raises(AppValidationError) as unchecked:
        await resume_scenario(
            db_session_factory,
            context,
            model=model,
            decisions=[
                ScenarioDecision(tool_call_id="create", decision="approved", override_args=fixed)
            ],
        )
    assert unchecked.value.details["error_code"] == "approval_review_required"
    assert account.created == []

    checks = await _review(db_session_factory, context, rejected)
    assert checks["ads"][0]["problems"] == [
        {
            "ad_group": f"{_C}/adGroups/22",
            "message": "Google says: Disapproved under the Destination Not Working policy.",
        }
    ]

    checks = await _review(db_session_factory, context, fixed)
    assert checks["ads"][0]["problems"] == []
    assert account.created == []

    # The card sends blank options as null, which doesn't change what Google checked.
    as_card_sends = deepcopy(fixed)
    as_card_sends["ads"][0]["mobile_final_url"] = None
    completed = await resume_scenario(
        db_session_factory,
        context,
        model=model,
        decisions=[
            ScenarioDecision(
                tool_call_id="create", decision="approved", override_args=as_card_sends
            )
        ],
    )

    assert completed.run.status == "completed"
    assert len(account.created) == 1
    sent = account.mutates[-1]["mutateOperations"][0]["adGroupAdOperation"]["create"]
    assert sent["adGroup"] == f"{_C}/adGroups/20"
    assert sent["ad"]["responsiveSearchAd"]["headlines"][0]["text"] == "Trail Runners"
    # One dry run on the proposal, one per check, and the send.
    assert [body["validateOnly"] for body in account.mutates] == [True, True, True, False]
