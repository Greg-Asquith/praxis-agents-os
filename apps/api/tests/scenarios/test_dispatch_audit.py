# apps/api/tests/scenarios/test_dispatch_auit.py

"""Dispatch and audit behavior through the real runtime lifecycle."""

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from tests.support.scenario import (
    ToolCall,
    ToolTurn,
    build_scenario_agent,
    run_scenario,
    scripted_model,
)


async def test_text_only_scenario_smoke(
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    context = await build_scenario_agent(db_session_factory)

    result = await run_scenario(
        db_session_factory,
        context,
        model=scripted_model(turns=["Hello from the scripted model."]),
        prompt="Hello",
    )

    assert result.output == "Hello from the scripted model."
    assert result.run.status == "completed"
    assert [message.role for message in result.messages] == ["user", "assistant"]
    assert result.audit_rows == []
    assert result.event_names()[-2:] == ["run.status", "done"]


async def test_successful_tool_dispatch_writes_one_digest_only_audit(
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    context = await build_scenario_agent(db_session_factory, tool_names=["test_add_numbers"])
    model = scripted_model(
        turns=[
            ToolTurn((ToolCall("test_add_numbers", {"a": 7, "b": 5}, "add-call"),)),
            "The total is 12.",
        ]
    )

    result = await run_scenario(db_session_factory, context, model=model)

    [audit] = result.audit_rows
    assert audit.status == "success"
    assert audit.details["outcome"] == "completed"
    assert audit.details["args_bytes"] > 0
    assert len(audit.details["args_sha256"]) == 64
    assert "a" not in audit.details and "b" not in audit.details
    assert len(result.tool_calls("test_add_numbers")) == 1
    assert result.run.status == "completed"


async def test_retrying_tool_failure_audits_failed_and_completes_after_retry(
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    context = await build_scenario_agent(db_session_factory, tool_names=["scenario_fail"])
    model = scripted_model(
        turns=[
            ToolTurn((ToolCall("scenario_fail", {}, "failure-call"),)),
            "I could not complete that operation.",
        ]
    )

    result = await run_scenario(db_session_factory, context, model=model)

    [audit] = result.audit_rows
    assert audit.status == "failure"
    assert audit.details["outcome"] == "failed"
    assert audit.details["error_code"] == "ToolRetryError"
    assert result.run.status == "completed"
    assert [message.role for message in result.messages] == [
        "user",
        "assistant",
        "tool",
        "assistant",
    ]


async def test_write_output_contract_mismatch_is_unverified_mutation(
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    context = await build_scenario_agent(db_session_factory, tool_names=["scenario_bad_write"])
    model = scripted_model(
        turns=[
            ToolTurn((ToolCall("scenario_bad_write", {}, "bad-write-call"),)),
            "The write result could not be verified.",
        ]
    )

    result = await run_scenario(db_session_factory, context, model=model)

    [audit] = result.audit_rows
    assert audit.status == "failure"
    assert audit.details["outcome"] == "unverified_mutation"
    assert audit.details["error_code"] == "OutputContractValidationError"
    assert result.run.status == "completed"
    assert result.output == "The write result could not be verified."
