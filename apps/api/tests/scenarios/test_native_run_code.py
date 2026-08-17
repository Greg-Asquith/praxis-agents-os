"""Provider-native run_code approval and scheduled-runtime scenarios."""

import pytest
from pydantic import SecretStr
from pydantic_ai import DeferredToolResults, ToolApproved
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from core.settings import settings
from services.agent_runs.domain import RUN_STATUS_AWAITING_APPROVAL
from services.agents.runtime.approval_state import load_suspended_run_state
from services.agents.runtime.tools.native import run_code as run_code_tools
from tests.support.scenario import (
    ToolCall,
    ToolTurn,
    build_scenario_agent,
    run_scenario,
    scripted_model,
)


def _enable_openai(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "ANTHROPIC_API_KEY", None)
    monkeypatch.setattr(settings, "GOOGLE_API_KEY", None)
    monkeypatch.setattr(settings, "OPENAI_API_KEY", SecretStr("sk-openai-test"))


def _script_run_code(monkeypatch: pytest.MonkeyPatch, executed: list[str]) -> None:
    async def fake_execution(*, deps, task: str, inputs, model_spec):
        del deps, inputs, model_spec
        executed.append(task)
        return "The computed total is 42.", [], []

    async def fake_persistence(deps, *, task, captured, input_file_ids, input_revision_ids):
        del deps, task, captured, input_file_ids, input_revision_ids
        return [], []

    monkeypatch.setattr(run_code_tools, "run_native_code_execution", fake_execution)
    monkeypatch.setattr(run_code_tools, "persist_sandbox_outputs", fake_persistence)


async def test_run_code_approval_suspends_and_resumes(
    db_session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _enable_openai(monkeypatch)
    executed: list[str] = []
    _script_run_code(monkeypatch, executed)
    context = await build_scenario_agent(
        db_session_factory,
        tool_names=["run_code"],
        tool_policies={"run_code": "approval"},
    )
    model = scripted_model(
        turns=[
            ToolTurn((ToolCall("run_code", {"task": "Sum the data"}, "run-code-approval"),)),
            "The approved computation completed.",
        ]
    )

    suspended = await run_scenario(db_session_factory, context, model=model)

    assert suspended.run.status == RUN_STATUS_AWAITING_APPROVAL
    assert executed == []
    state = load_suspended_run_state(suspended.run)
    resumed = await run_scenario(
        db_session_factory,
        context,
        model=model,
        prompt=None,
        expected_status=RUN_STATUS_AWAITING_APPROVAL,
        message_history=state.message_history,
        deferred_tool_results=DeferredToolResults(
            approvals={state.pending_tool_call_ids[0]: ToolApproved()}
        ),
    )

    assert resumed.run.status == "completed"
    assert executed == ["Sum the data"]
    assert {row.details["outcome"] for row in resumed.audit_rows} == {
        "approval_requested",
        "completed",
    }


@pytest.mark.parametrize(
    ("policy", "expected_status", "expected_tasks"),
    [
        ("auto", "completed", ["Build the scheduled digest"]),
        ("approval", RUN_STATUS_AWAITING_APPROVAL, []),
    ],
)
async def test_scheduled_run_code_respects_tool_policy_for_internal_execution(
    db_session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
    policy: str,
    expected_status: str,
    expected_tasks: list[str],
) -> None:
    _enable_openai(monkeypatch)
    executed: list[str] = []
    _script_run_code(monkeypatch, executed)
    context = await build_scenario_agent(
        db_session_factory,
        tool_names=["run_code"],
        tool_policies={"run_code": policy},
        trigger="scheduled",
        metadata={"envelope": {"side_effect_policy": "require_approval"}},
    )
    turns: list[ToolTurn | str] = [
        ToolTurn((ToolCall("run_code", {"task": "Build the scheduled digest"}),))
    ]
    if policy == "auto":
        turns.append("The scheduled digest is ready.")

    result = await run_scenario(
        db_session_factory,
        context,
        model=scripted_model(turns=turns),
    )

    assert result.run.status == expected_status
    assert executed == expected_tasks
