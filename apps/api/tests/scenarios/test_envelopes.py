# apps/api/tests/scenarios/test_envelopes.py

"""Server-minted run-envelope scenarios for external writes."""

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from tests.support.scenario import (
    ToolCall,
    ToolTurn,
    build_scenario_agent,
    run_scenario,
    scripted_model,
)


async def test_scheduled_external_write_requires_approval(
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    context = await build_scenario_agent(
        db_session_factory,
        tool_names=["scenario_external_write"],
        trigger="scheduled",
        metadata={"envelope": {"side_effect_policy": "require_approval"}},
    )

    result = await run_scenario(
        db_session_factory,
        context,
        model=scripted_model(
            turns=[ToolTurn((ToolCall("scenario_external_write", {"value": "scheduled"}),))]
        ),
    )

    assert result.run.status == "awaiting_approval"
    [audit] = result.audit_rows
    assert audit.status == "pending"
    assert audit.details["outcome"] == "approval_requested"
    assert "tool.approval_required" in result.event_names()


async def test_deny_envelope_blocks_external_write_and_audits_denial(
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    context = await build_scenario_agent(
        db_session_factory,
        tool_names=["scenario_external_write"],
        trigger="scheduled",
        metadata={"envelope": {"side_effect_policy": "deny"}},
    )

    result = await run_scenario(
        db_session_factory,
        context,
        model=scripted_model(
            turns=[
                ToolTurn((ToolCall("scenario_external_write", {"value": "blocked"}),)),
                "The run policy denied that write.",
            ]
        ),
    )

    assert result.run.status == "completed"
    [audit] = result.audit_rows
    assert audit.status == "denied"
    assert audit.details["outcome"] == "denied_envelope"
    assert result.output == "The run policy denied that write."
