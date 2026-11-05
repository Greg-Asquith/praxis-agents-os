# apps/api/tests/scenarios/test_progress_reviews.py

"""Progress reviews decide whether a run carries on past its step limit."""

import asyncio
import json
import re

import pytest
from pydantic_ai import DeferredToolResults, ToolApproved
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from core.settings import settings
from models.agent import Agent
from models.agent_run import AgentRun
from models.audit_event import AuditEvent
from services.agents.runtime.approval_state import load_suspended_run_state
from services.agents.runtime.progress_review.checkpoint import (
    GRANTS_USED_REASON,
    REVIEW_UNAVAILABLE_REASON,
)
from services.agents.runtime.progress_review.grant import PROGRESS_REVIEWS_KEY
from services.agents.runtime.progress_review.verdict import STEER_TEXT, ProgressReview
from services.agents.runtime.run_persistence import restored_run_usage
from services.agents.runtime.usage_limits import BudgetLimitExceeded
from tests.support.scenario import (
    ScenarioContext,
    ToolCall,
    ToolTurn,
    build_scenario_agent,
    run_scenario,
    scripted_model,
)

REVIEWER = "services.agents.runtime.progress_review.review.review_progress"
WRITE = ToolTurn((ToolCall("scenario_external_write", {"value": "ok"}),))


async def _agent_with_steps(
    session_factory: async_sessionmaker[AsyncSession], max_steps: int, **kwargs
) -> ScenarioContext:
    context = await build_scenario_agent(
        session_factory, tool_names=["scenario_external_write"], **kwargs
    )
    async with session_factory() as db:
        agent = await db.get(Agent, context.agent_id)
        agent.max_steps = max_steps
        await db.commit()
    return context


def _reviewer(verdict: str, calls: list[int] | None = None, guidance: str | None = None):
    async def review(deps, digest) -> ProgressReview:
        if calls is not None:
            calls.append(int(re.search(r"(\d+) model requests used", digest.text).group(1)))
        return ProgressReview(verdict=verdict, reason="Reviewed.", guidance=guidance)

    return review


async def test_steer_extends_the_run_and_reaches_the_next_request(
    committed_db_session_factory, monkeypatch
):
    context = await _agent_with_steps(committed_db_session_factory, 2)
    monkeypatch.setattr(REVIEWER, _reviewer("steer_wrap_up", guidance="Report the totals."))
    seen = []
    model = scripted_model(turns=[WRITE, WRITE, "Done."], seen_requests=seen)

    result = await run_scenario(committed_db_session_factory, context, model=model)

    assert result.run.outcome == "success"
    assert result.output == "Done."
    steer = STEER_TEXT["steer_wrap_up"]
    assert steer not in str(seen[1][0])
    assert steer in str(seen[2][0])
    assert "Report the totals." in str(seen[2][0])
    assert steer in json.dumps([message.parts for message in result.messages])
    saved = result.run.metadata_json[PROGRESS_REVIEWS_KEY]
    assert saved["granted"] == 2
    assert [review["verdict"] for review in saved["reviews"]] == ["steer_wrap_up"]
    async with committed_db_session_factory() as db:
        audits = list(
            await db.scalars(
                select(AuditEvent).where(AuditEvent.resource_id == str(context.run_id))
            )
        )
    [audit] = [event for event in audits if event.details.get("operation") == "progress_review"]
    assert (audit.actor_type, audit.details["verdict"], audit.details["requests_granted"]) == (
        "system",
        "steer_wrap_up",
        2,
    )


@pytest.mark.parametrize("failure", ["model_unavailable", "times_out"])
async def test_reviewer_failure_hands_the_run_back_to_a_person(
    committed_db_session_factory, monkeypatch, failure
):
    context = await _agent_with_steps(committed_db_session_factory, 1)
    if failure == "times_out":
        monkeypatch.setattr(settings, "AGENT_RUN_PROGRESS_REVIEW_TIMEOUT_SECONDS", 0.01)

        async def hangs(deps, digest) -> ProgressReview:
            await asyncio.Event().wait()

        monkeypatch.setattr(REVIEWER, hangs)
    model = scripted_model(turns=[WRITE, "Unreachable."])

    with pytest.raises(BudgetLimitExceeded):
        await run_scenario(committed_db_session_factory, context, model=model)

    async with committed_db_session_factory() as db:
        run = await db.get(AgentRun, context.run_id)
    assert run.outcome == "budget_exhausted"
    evidence = run.completion_json["progress_review"]
    assert evidence["verdict"] == "ask_person"
    assert evidence["reviews_used"] == 1
    assert evidence["reason"] == REVIEW_UNAVAILABLE_REASON


async def test_grant_cap_asks_a_person_without_calling_the_reviewer(
    committed_db_session_factory, monkeypatch
):
    monkeypatch.setattr(settings, "AGENT_RUN_PROGRESS_REVIEW_MAX_GRANTS", 1)
    context = await _agent_with_steps(committed_db_session_factory, 1)
    calls: list[int] = []
    monkeypatch.setattr(REVIEWER, _reviewer("continue", calls))
    model = scripted_model(turns=[WRITE, WRITE, "Unreachable."])

    with pytest.raises(BudgetLimitExceeded):
        await run_scenario(committed_db_session_factory, context, model=model)

    async with committed_db_session_factory() as db:
        run = await db.get(AgentRun, context.run_id)
    assert calls == [1]
    assert run.completion_json["tripped_budget"]["limit"] == 2
    assert run.completion_json["progress_review"] == {
        "verdict": "ask_person",
        "reason": GRANTS_USED_REASON,
        "reviews_used": 2,
    }


async def test_schedule_request_cap_trips_without_a_review(
    committed_db_session_factory, monkeypatch
):
    context = await _agent_with_steps(
        committed_db_session_factory,
        1,
        trigger="scheduled",
        metadata={
            "completion_contract": {"required": False, "max_requests": 1},
            "envelope": {"side_effect_policy": "allow"},
        },
    )
    calls: list[int] = []
    monkeypatch.setattr(REVIEWER, _reviewer("continue", calls))
    model = scripted_model(turns=[WRITE, "Unreachable."])

    with pytest.raises(BudgetLimitExceeded):
        await run_scenario(committed_db_session_factory, context, model=model)

    async with committed_db_session_factory() as db:
        run = await db.get(AgentRun, context.run_id)
    assert calls == []
    assert "progress_review" not in run.completion_json


async def test_grant_survives_an_approval_pause(committed_db_session_factory, monkeypatch):
    context = await _agent_with_steps(committed_db_session_factory, 1)
    async with committed_db_session_factory() as db:
        agent = await db.get(Agent, context.agent_id)
        agent.tool_names = ["scenario_external_write", "scenario_fail"]
        agent.tool_policies = {"scenario_external_write": "approval"}
        await db.commit()
    calls: list[int] = []
    monkeypatch.setattr(REVIEWER, _reviewer("continue", calls))
    model = scripted_model(
        turns=[
            ToolTurn((ToolCall("scenario_fail", {}),)),
            ToolTurn((ToolCall("scenario_external_write", {"value": "ok"}, "approval-call"),)),
            "Done.",
        ]
    )

    parked = await run_scenario(committed_db_session_factory, context, model=model)
    assert parked.run.status == "awaiting_approval"
    assert parked.run.metadata_json[PROGRESS_REVIEWS_KEY]["granted"] == 1
    state = load_suspended_run_state(parked.run)

    resumed = await run_scenario(
        committed_db_session_factory,
        context,
        model=model,
        prompt=None,
        expected_status="awaiting_approval",
        message_history=state.message_history,
        deferred_tool_results=DeferredToolResults(
            approvals={state.pending_tool_call_ids[0]: ToolApproved()}
        ),
        usage=restored_run_usage(parked.run),
    )

    assert resumed.run.outcome == "success"
    assert calls == [1, 2]
    assert resumed.run.metadata_json[PROGRESS_REVIEWS_KEY]["granted"] == 2
