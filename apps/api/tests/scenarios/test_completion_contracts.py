"""Completion-report verdicts through the real scheduled runtime pipeline."""

import pytest
from pydantic_ai import UsageLimitExceeded
from pydantic_ai.messages import ModelRequest, UserPromptPart
from pydantic_ai.models.test import TestModel
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from models.agent_run import AgentRun
from models.workspace import WorkspaceRole
from services.agents.runtime.completion_contract import REPORT_COMPLETION_TOOL_NAME
from tests.support.scenario import (
    ToolCall,
    ToolTurn,
    build_scenario_agent,
    run_scenario,
    scripted_model,
)

pytestmark = pytest.mark.asyncio

_CONTRACT = {
    "required": True,
    "criteria": ["A report was created", "Every account was reviewed"],
}


@pytest.mark.parametrize(
    ("report_status", "expected_outcome"),
    [("pass", "success"), ("fail", "gate_failed")],
)
async def test_required_completion_report_controls_terminal_verdict(
    committed_db_session_factory: async_sessionmaker[AsyncSession],
    report_status: str,
    expected_outcome: str,
) -> None:
    context = await build_scenario_agent(
        committed_db_session_factory,
        trigger="scheduled",
        metadata={
            "completion_contract": _CONTRACT,
            "envelope": {"side_effect_policy": "deny"},
        },
        role=WorkspaceRole.READ_ONLY,
    )
    seen_requests = []
    model = scripted_model(
        turns=[
            ToolTurn(
                calls=(
                    ToolCall(
                        name=REPORT_COMPLETION_TOOL_NAME,
                        args={
                            "status": report_status,
                            "summary": f"Completion check {report_status}ed.",
                            "evidence": ["Checked the generated report."],
                        },
                    ),
                )
            ),
            "Scheduled work finished.",
        ],
        seen_requests=seen_requests,
    )

    result = await run_scenario(
        committed_db_session_factory,
        context,
        model=model,
    )

    assert result.run.status == "completed"
    assert result.run.outcome == expected_outcome
    assert result.run.completion_json == {
        "status": report_status,
        "summary": f"Completion check {report_status}ed.",
        "evidence": ["Checked the generated report."],
    }
    assert REPORT_COMPLETION_TOOL_NAME in {tool.name for tool in seen_requests[0][1].function_tools}
    request_info = str(seen_requests[0][1])
    assert "## Completion Contract" in request_info
    assert "1. A report was created" in request_info
    assert "2. Every account was reviewed" in request_info
    user_prompt_text = "\n".join(
        part.content
        for message in seen_requests[0][0]
        if isinstance(message, ModelRequest)
        for part in message.parts
        if isinstance(part, UserPromptPart) and isinstance(part.content, str)
    )
    assert "## Completion Contract" not in user_prompt_text
    assert len(result.tool_calls(REPORT_COMPLETION_TOOL_NAME)) == 1
    [report_audit] = result.audit_rows
    assert report_audit.status == "success"
    assert report_audit.details["outcome"] == "completed"


async def test_missing_required_completion_report_fails_gate_without_failing_run(
    committed_db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    context = await build_scenario_agent(
        committed_db_session_factory,
        trigger="scheduled",
        metadata={"completion_contract": _CONTRACT},
    )

    result = await run_scenario(
        committed_db_session_factory,
        context,
        model=scripted_model(turns=["Scheduled work finished without a report."]),
    )

    assert result.run.status == "completed"
    assert result.run.outcome == "gate_failed"
    assert result.run.error_code is None
    assert result.run.completion_json == {"error_code": "missing_completion_report"}


async def test_first_completion_report_remains_authoritative_when_model_retries_with_opposite_verdict(
    committed_db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    context = await build_scenario_agent(
        committed_db_session_factory,
        trigger="scheduled",
        metadata={"completion_contract": _CONTRACT},
    )
    first_report = {
        "status": "fail",
        "summary": "One account was not reviewed.",
        "evidence": ["Account 2 was unavailable."],
    }

    result = await run_scenario(
        committed_db_session_factory,
        context,
        model=scripted_model(
            turns=[
                ToolTurn(
                    calls=(
                        ToolCall(
                            name=REPORT_COMPLETION_TOOL_NAME,
                            args=first_report,
                            call_id="first-completion-report",
                        ),
                    )
                ),
                ToolTurn(
                    calls=(
                        ToolCall(
                            name=REPORT_COMPLETION_TOOL_NAME,
                            args={
                                "status": "pass",
                                "summary": "All accounts were reviewed.",
                                "evidence": ["Account 2 recovered."],
                            },
                            call_id="duplicate-completion-report",
                        ),
                    )
                ),
                "Scheduled work finished.",
            ]
        ),
    )

    assert result.run.status == "completed"
    assert result.run.outcome == "gate_failed"
    assert result.run.completion_json == first_report
    assert len(result.tool_calls(REPORT_COMPLETION_TOOL_NAME)) == 2
    assert [row.status for row in result.audit_rows] == ["success", "failure"]


async def test_completion_report_tool_is_absent_without_required_contract(
    committed_db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    context = await build_scenario_agent(
        committed_db_session_factory,
        metadata={"completion_contract": _CONTRACT},
    )
    seen_requests = []

    result = await run_scenario(
        committed_db_session_factory,
        context,
        model=scripted_model(turns=["Interactive work finished."], seen_requests=seen_requests),
    )

    assert result.run.outcome == "success"
    assert REPORT_COMPLETION_TOOL_NAME not in {
        tool.name for tool in seen_requests[0][1].function_tools
    }


async def test_scheduled_token_budget_records_the_tripped_budget(
    committed_db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    context = await build_scenario_agent(
        committed_db_session_factory,
        trigger="scheduled",
        metadata={
            "completion_contract": {
                "required": False,
                "criteria": [],
                "max_total_tokens": 1,
            }
        },
    )

    with pytest.raises(UsageLimitExceeded):
        await run_scenario(
            committed_db_session_factory,
            context,
            model=TestModel(call_tools=[]),
        )

    async with committed_db_session_factory() as db:
        run = await db.get(AgentRun, context.run_id)

    assert run is not None
    assert run.status == "failed"
    assert run.outcome == "budget_exhausted"
    assert run.error_code == "usage_limit_exceeded"
    assert run.completion_json == {
        "error_code": "usage_limit_exceeded",
        "tripped_budget": {"kind": "total_tokens", "limit": 1},
    }
