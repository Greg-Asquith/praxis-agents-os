# apps/api/tests/scenarios/test_history_trimming.py

"""Cache-stable history behavior through consecutive runtime turns."""

import importlib

import pytest
from pydantic_ai import DeferredToolRequests, DeferredToolResults, ToolApproved
from pydantic_ai.messages import (
    ModelRequest,
    ModelResponse,
    ToolCallPart,
    UserPromptPart,
)
from pydantic_ai.models.function import AgentInfo, FunctionModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from core.settings import settings
from models.agent import Agent
from models.agent_run import AgentRun
from models.conversation_summary import ConversationSummary
from models.jobs import Job
from services.agent_runs.domain import RUN_STATUS_AWAITING_APPROVAL
from services.agents.runtime.approval_state import load_suspended_run_state
from services.agents.runtime.history import AUTOMATIC_SUMMARY_PREFIX
from services.conversation_summaries.domain import SUMMARIZE_HISTORY_JOB_KIND
from services.conversation_summaries.summarize_history_job import summarize_history_job
from tests.support.scenario import (
    ToolCall,
    ToolTurn,
    build_scenario_agent,
    next_scenario_run,
    run_scenario,
    scripted_model,
)


async def test_consecutive_turns_keep_a_stable_trim_watermark(
    db_session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "AGENT_HISTORY_MAX_TURNS", 6)
    monkeypatch.setattr(settings, "AGENT_HISTORY_KEEP_TURNS", 2)
    context = await build_scenario_agent(db_session_factory)
    requests_by_turn = []

    for index in range(9):
        if index:
            context = await next_scenario_run(db_session_factory, context)
        seen = []
        result = await run_scenario(
            db_session_factory,
            context,
            model=scripted_model(turns=[f"reply {index}"], seen_requests=seen),
            prompt=f"turn {index}",
        )
        assert result.run.status == "completed"
        requests_by_turn.append(seen[0][0])

    penultimate = _boundary_texts(requests_by_turn[-2])
    final = _boundary_texts(requests_by_turn[-1])
    assert penultimate[0] == final[0] == "turn 4"
    assert penultimate[-1] == "turn 7"
    assert final[-1] == "turn 8"


async def test_long_conversation_enqueues_injects_and_chains_summaries(
    db_session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "AGENT_HISTORY_MAX_TURNS", 6)
    monkeypatch.setattr(settings, "AGENT_HISTORY_KEEP_TURNS", 2)
    context = await build_scenario_agent(db_session_factory)
    requests_by_turn = []
    processed_jobs = set()

    for index in range(12):
        if index:
            context = await next_scenario_run(db_session_factory, context)
        seen = []
        result = await run_scenario(
            db_session_factory,
            context,
            model=scripted_model(turns=[f"reply {index}"], seen_requests=seen),
            prompt=f"turn {index}",
        )
        assert result.run.status == "completed"
        requests_by_turn.append(seen[0][0])

        async with db_session_factory() as db:
            jobs = list(
                (
                    await db.scalars(
                        select(Job)
                        .where(
                            Job.kind == SUMMARIZE_HISTORY_JOB_KIND,
                            Job.subject_id == context.conversation_id,
                        )
                        .order_by(Job.created_at)
                    )
                ).all()
            )
            for job in jobs:
                if job.id in processed_jobs:
                    continue
                await summarize_history_job(
                    db,
                    job,
                    model=_summary_model(f"summary at turn {index}"),
                )
                processed_jobs.add(job.id)
            await db.commit()

    summary_messages = [
        part.content
        for messages in requests_by_turn
        for message in messages
        if isinstance(message, ModelRequest)
        for part in message.parts
        if isinstance(part, UserPromptPart)
        and isinstance(part.content, str)
        and part.content.startswith(AUTOMATIC_SUMMARY_PREFIX)
    ]
    assert len(processed_jobs) == 2
    assert any("summary at turn 7" in content for content in summary_messages)
    assert any("summary at turn 10" in content for content in summary_messages)
    async with db_session_factory() as db:
        summaries = list(
            (
                await db.scalars(
                    select(ConversationSummary)
                    .where(ConversationSummary.conversation_id == context.conversation_id)
                    .order_by(ConversationSummary.created_at)
                )
            ).all()
        )
    assert len(summaries) == 2
    assert summaries[1].source_message_count > summaries[0].source_message_count


async def test_approval_resume_reuses_the_exact_watermark_summary(
    db_session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "AGENT_HISTORY_MAX_TURNS", 6)
    monkeypatch.setattr(settings, "AGENT_HISTORY_KEEP_TURNS", 2)
    context = await build_scenario_agent(
        db_session_factory,
        tool_names=["test_add_numbers"],
        tool_policies={"test_add_numbers": "approval"},
    )

    for index in range(8):
        if index:
            context = await next_scenario_run(db_session_factory, context)
        result = await run_scenario(
            db_session_factory,
            context,
            model=scripted_model(turns=[f"reply {index}"]),
            prompt=f"turn {index}",
        )
        assert result.run.status == "completed"

    async with db_session_factory() as db:
        job = await db.scalar(
            select(Job).where(
                Job.kind == SUMMARIZE_HISTORY_JOB_KIND,
                Job.subject_id == context.conversation_id,
            )
        )
        assert job is not None
        await summarize_history_job(
            db,
            job,
            model=_summary_model("Stable summary before approval."),
        )
        await db.commit()

    context = await next_scenario_run(db_session_factory, context)
    suspended = await run_scenario(
        db_session_factory,
        context,
        model=scripted_model(
            turns=[
                ToolTurn(
                    calls=(
                        ToolCall(
                            name="test_add_numbers",
                            args={"a": 2, "b": 3},
                            call_id="approval-call",
                        ),
                    )
                )
            ]
        ),
        prompt="Add the numbers.",
    )
    assert isinstance(suspended.output, DeferredToolRequests)

    async with db_session_factory() as db:
        run = await db.get(AgentRun, context.run_id)
        assert run is not None
        suspended_state = load_suspended_run_state(run)

    resumed_requests = []
    resumed = await run_scenario(
        db_session_factory,
        context,
        model=scripted_model(turns=["approved"], seen_requests=resumed_requests),
        prompt=None,
        expected_status=RUN_STATUS_AWAITING_APPROVAL,
        message_history=suspended_state.message_history,
        deferred_tool_results=DeferredToolResults(approvals={"approval-call": ToolApproved()}),
    )

    assert resumed.run.status == "completed"
    assert "Stable summary before approval." in _automatic_summary_text(resumed_requests[0][0])


async def test_summary_enqueue_failure_does_not_change_completed_run(
    db_session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "AGENT_HISTORY_MAX_TURNS", 2)
    monkeypatch.setattr(settings, "AGENT_HISTORY_KEEP_TURNS", 1)
    context = await build_scenario_agent(db_session_factory)

    for index in range(3):
        if index:
            context = await next_scenario_run(db_session_factory, context)
        result = await run_scenario(
            db_session_factory,
            context,
            model=scripted_model(turns=[f"reply {index}"]),
            prompt=f"turn {index}",
        )
        assert result.run.status == "completed"

    enqueue_module = importlib.import_module(
        "services.conversation_summaries.safe_enqueue_history_summary"
    )

    async def fail_enqueue(*_args, **_kwargs):
        raise RuntimeError("summary queue unavailable")

    monkeypatch.setattr(enqueue_module, "enqueue_history_summary", fail_enqueue)
    context = await next_scenario_run(db_session_factory, context)
    result = await run_scenario(
        db_session_factory,
        context,
        model=scripted_model(turns=["still completed"]),
        prompt="turn 3",
    )

    assert result.run.status == "completed"
    assert result.output == "still completed"


async def test_azure_history_uses_deployment_context_budget(
    db_session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "AGENT_HISTORY_MAX_TURNS", 4)
    monkeypatch.setattr(settings, "AGENT_HISTORY_KEEP_TURNS", 2)
    monkeypatch.setattr(settings, "AZURE_OPENAI_CONTEXT_WINDOW", 1)
    monkeypatch.setattr(settings, "AZURE_OPENAI_CHARS_PER_TOKEN", 4.0)
    context = await build_scenario_agent(db_session_factory)
    async with db_session_factory() as db:
        agent = await db.get(Agent, context.agent_id)
        assert agent is not None
        agent.model_provider = "azure"
        agent.model = "gpt-5.6-luna"
        agent.azure_deployment = "test-luna-deployment"
        await db.commit()

    seen_requests = []
    for index in range(4):
        if index:
            context = await next_scenario_run(db_session_factory, context)
        seen = []
        result = await run_scenario(
            db_session_factory,
            context,
            model=scripted_model(turns=[f"reply {index}"], seen_requests=seen),
            prompt=f"turn {index}",
        )
        assert result.run.status == "completed"
        seen_requests.append(seen[0][0])

    assert _boundary_texts(seen_requests[-1])[0] == "turn 2"


def _summary_model(summary: str) -> FunctionModel:
    async def respond(_messages, info: AgentInfo) -> ModelResponse:
        return ModelResponse(
            parts=[
                ToolCallPart(
                    tool_name=info.output_tools[0].name,
                    args={"summary": summary},
                    tool_call_id="summary-output",
                )
            ]
        )

    return FunctionModel(respond, model_name="scenario-summary")


def _automatic_summary_text(messages) -> str:
    return "\n".join(
        part.content
        for message in messages
        if isinstance(message, ModelRequest)
        for part in message.parts
        if isinstance(part, UserPromptPart)
        and isinstance(part.content, str)
        and part.content.startswith(AUTOMATIC_SUMMARY_PREFIX)
    )


def _boundary_texts(messages):
    return [
        part.content
        for message in messages
        if isinstance(message, ModelRequest)
        for part in message.parts
        if isinstance(part, UserPromptPart) and isinstance(part.content, str)
    ]
