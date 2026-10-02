"""End-to-end code-mode composition and defense-in-depth scenarios."""

import asyncio
import json
from collections.abc import Iterator
from pathlib import Path
from typing import Annotated, Any, Literal
from unittest.mock import AsyncMock

import pytest
from pydantic import BaseModel, Field
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from core.exceptions.general import ConflictError
from core.settings import settings
from models.agent import Agent
from models.agent_run import AgentRun
from models.conversation import Conversation, ConversationMessage
from models.files import File, FileRevision
from models.user import User
from models.workspace import Workspace, WorkspaceMembership, WorkspaceRole
from services.agent_runs.get_approval_state import get_agent_run_approval_state
from services.agent_runs.resume_run_stream import (
    resume_agent_run_stream,
)
from services.agent_runs.schemas import AgentRunResumeDecision, AgentRunResumeRequest
from services.agents.runtime.approval_state import load_suspended_run_state
from services.agents.runtime.code_mode.executor import MontyExecutor, close_code_mode_executor
from services.agents.runtime.code_mode.state import (
    CODE_MODE_STATE_METADATA_KEY,
    CodeModeResumeRequiresRecoveryError,
)
from services.agents.runtime.dispatch import digest_args
from services.agents.runtime.run_manager import run_task_registry
from services.agents.runtime.staged_tool_content import (
    WRITE_FILE_CONTENT_REF_ARG,
    resolve_staged_write_content,
)
from services.agents.runtime.tools.code_mode import (
    RUN_CODE_TOOL_NAME,
)
from services.agents.runtime.tools.contract import (
    TOOL_EFFECT_SCOPE_EXTERNAL,
    TOOL_EFFECT_WRITE,
    TOOL_EGRESS_EXTERNAL_WRITE,
    TOOL_POLICY_APPROVAL,
    TOOL_POLICY_AUTO,
    RuntimeToolDefinition,
    ToolFieldColumn,
    ToolFieldPresentation,
    ToolPresentation,
)
from services.agents.runtime.tools.registry import RUNTIME_TOOL_CATALOG
from services.agents.runtime.untrusted import UNTRUSTED_CONTENT_START, UntrustedContent
from services.conversations.shared_projection import project_shared_message
from services.files.utils import private_ref_from_key
from services.storage.errors import StorageNotFoundError
from services.storage.factory import get_storage_provider
from tests.support.approvals import ScenarioDecision, compile_scenario_decisions
from tests.support.scenario import (
    ToolCall,
    ToolTurn,
    build_scenario_agent,
    resume_code_mode_scenario,
    run_scenario,
    scripted_model,
)
from tests.support.storage import reset_storage_provider_cache

_FIXTURE_PATH = (
    Path(__file__).parents[1] / "fixtures" / "prompt_injection" / "hostile_tool_result.json"
)
_TOOL_NAMES = (
    "scenario_code_read_first",
    "scenario_code_read_second",
    "scenario_code_hostile_read",
    "scenario_code_forced_write",
    "scenario_code_invalid_write",
    "scenario_code_batch_write",
)


class _WriteResult(BaseModel):
    ok: bool


class _BatchRow(BaseModel):
    text: str
    match_type: Literal["EXACT", "PHRASE", "BROAD"]


class _BatchWriteResult(BaseModel):
    applied: int


@pytest.fixture
def code_mode_local_storage(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setattr(settings, "STORAGE_PROVIDER", "local_fs")
    monkeypatch.setattr(settings, "LOCAL_STORAGE_ROOT", str(tmp_path))
    monkeypatch.setattr(settings, "APP_BASE_URL", "http://testserver")
    reset_storage_provider_cache()
    try:
        yield
    finally:
        reset_storage_provider_cache()


@pytest.fixture
def code_mode_scenario_tools() -> dict[str, Any]:
    effects: list[str] = []
    batch_effects: list[list[dict[str, str]]] = []
    hostile_payload = json.loads(_FIXTURE_PATH.read_text(encoding="utf-8"))

    async def read_first(*, value: str) -> dict[str, str]:
        return {"value": value, "source": "first"}

    async def read_second(*, value: str) -> dict[str, str]:
        return {"value": value.upper(), "source": "second"}

    async def hostile_read() -> UntrustedContent:
        return UntrustedContent(
            source_kind="code_mode_fixture",
            source_ref="hostile_tool_result.json",
            content=json.dumps(hostile_payload, sort_keys=True),
        )

    async def forced_write(*, value: str) -> dict[str, bool]:
        effects.append(value)
        return {"ok": True}

    async def invalid_write(*, value: str) -> dict[str, str]:
        effects.append(value)
        return {"unexpected": "shape"}

    async def batch_write(
        *,
        keywords: Annotated[list[_BatchRow], Field(min_length=1, max_length=500)],
    ) -> dict[str, int]:
        rows = [row.model_dump() for row in keywords]
        batch_effects.append(rows)
        return {"applied": len(rows)}

    definitions = (
        RuntimeToolDefinition(
            name="scenario_code_read_first",
            function=read_first,
            provider="test",
            description="Read the first deterministic scenario value.",
            code_eligible=True,
            configurable=False,
        ),
        RuntimeToolDefinition(
            name="scenario_code_read_second",
            function=read_second,
            provider="test",
            description="Read the second deterministic scenario value.",
            code_eligible=True,
            configurable=False,
        ),
        RuntimeToolDefinition(
            name="scenario_code_hostile_read",
            function=hostile_read,
            provider="test",
            description="Read an untrusted deterministic scenario result.",
            code_eligible=True,
            configurable=False,
        ),
        RuntimeToolDefinition(
            name="scenario_code_forced_write",
            function=forced_write,
            provider="test",
            description="Perform a test-only external write.",
            effect=TOOL_EFFECT_WRITE,
            effect_scope=TOOL_EFFECT_SCOPE_EXTERNAL,
            egress=TOOL_EGRESS_EXTERNAL_WRITE,
            code_eligible=True,
            default_policy=TOOL_POLICY_APPROVAL,
            configurable=False,
            presentation=ToolPresentation(
                arg_fields=(ToolFieldPresentation(key="value", label="Value", editable=True),)
            ),
        ),
        RuntimeToolDefinition(
            name="scenario_code_invalid_write",
            function=invalid_write,
            provider="test",
            description="Perform a write that returns an invalid output shape.",
            effect=TOOL_EFFECT_WRITE,
            effect_scope=TOOL_EFFECT_SCOPE_EXTERNAL,
            egress=TOOL_EGRESS_EXTERNAL_WRITE,
            code_eligible=True,
            default_policy=TOOL_POLICY_APPROVAL,
            configurable=False,
            output_model=_WriteResult,
        ),
        RuntimeToolDefinition(
            name="scenario_code_batch_write",
            function=batch_write,
            provider="test",
            description="Apply one bounded batch of test keyword rows.",
            effect=TOOL_EFFECT_WRITE,
            effect_scope=TOOL_EFFECT_SCOPE_EXTERNAL,
            egress=TOOL_EGRESS_EXTERNAL_WRITE,
            code_eligible=True,
            default_policy=TOOL_POLICY_APPROVAL,
            configurable=False,
            output_model=_BatchWriteResult,
            presentation=ToolPresentation(
                arg_fields=(
                    ToolFieldPresentation(
                        key="keywords",
                        label="Keywords",
                        format="records",
                        editable=True,
                        min_rows=1,
                        columns=(
                            ToolFieldColumn(key="text", label="Keyword", required=True),
                            ToolFieldColumn(
                                key="match_type",
                                label="Match Type",
                                options=("EXACT", "PHRASE", "BROAD"),
                                required=True,
                            ),
                        ),
                    ),
                )
            ),
        ),
    )
    for definition in definitions:
        RUNTIME_TOOL_CATALOG[definition.name] = definition
    try:
        yield {
            "definitions": definitions,
            "effects": effects,
            "batch_effects": batch_effects,
            "hostile_payload": hostile_payload,
        }
    finally:
        for name in _TOOL_NAMES:
            RUNTIME_TOOL_CATALOG.pop(name, None)


async def test_multi_read_script_completes_beside_direct_tools_with_nested_audits(
    db_session_factory: async_sessionmaker[AsyncSession],
    code_mode_scenario_tools: dict[str, Any],
) -> None:
    del code_mode_scenario_tools
    seen_requests = []
    context = await build_scenario_agent(
        db_session_factory,
        tool_names=["scenario_code_read_first", "scenario_code_read_second"],
    )

    result = await run_scenario(
        db_session_factory,
        context,
        model=scripted_model(
            turns=[
                ToolTurn(
                    (
                        ToolCall(
                            RUN_CODE_TOOL_NAME,
                            {
                                "code": (
                                    "first = await scenario_code_read_first(value='north')\n"
                                    "await scenario_code_read_second(value=first['value'])"
                                )
                            },
                            "workflow-call",
                        ),
                    )
                ),
                "The compared value is NORTH.",
            ],
            seen_requests=seen_requests,
        ),
    )

    first_request_tools = {tool.name for tool in seen_requests[0][1].function_tools}
    assert {
        RUN_CODE_TOOL_NAME,
        "scenario_code_read_first",
        "scenario_code_read_second",
    }.issubset(first_request_tools)
    assert len(seen_requests) == 2
    nested_audits = [
        row
        for row in result.audit_rows
        if row.details.get("parent_tool_call_id") == "workflow-call"
    ]
    ordered_nested_audits = sorted(nested_audits, key=lambda row: row.resource_id)
    assert [row.tool_name for row in ordered_nested_audits] == [
        "scenario_code_read_first",
        "scenario_code_read_second",
    ]
    assert all(len(row.details["args_sha256"]) == 64 for row in ordered_nested_audits)
    assert result.event_names().count("workflow.state") == 2
    assert result.output == "The compared value is NORTH."


async def test_script_cannot_call_a_tool_the_agent_has_not_mounted(
    db_session_factory: async_sessionmaker[AsyncSession],
    code_mode_scenario_tools: dict[str, Any],
) -> None:
    del code_mode_scenario_tools
    context = await build_scenario_agent(
        db_session_factory,
        tool_names=["scenario_code_read_first"],
    )

    result = await run_scenario(
        db_session_factory,
        context,
        model=scripted_model(
            turns=[
                ToolTurn(
                    (
                        ToolCall(
                            RUN_CODE_TOOL_NAME,
                            {
                                "code": (
                                    "try:\n"
                                    "    await scenario_code_read_second(value='north')\n"
                                    "    outcome = 'called'\n"
                                    "except NameError as exc:\n"
                                    "    outcome = str(exc)\n"
                                    "outcome"
                                )
                            },
                            "workflow-call",
                        ),
                    )
                ),
                "That tool isn't available.",
            ],
        ),
    )

    [workflow] = result.tool_returns(RUN_CODE_TOOL_NAME)
    assert "scenario_code_read_second" in str(workflow["content"])
    assert "called" not in str(workflow["content"])
    assert not any(row.tool_name == "scenario_code_read_second" for row in result.audit_rows)


async def test_repeated_script_failures_reach_the_model_without_failing_the_run(
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    context = await build_scenario_agent(db_session_factory)

    result = await run_scenario(
        db_session_factory,
        context,
        model=scripted_model(
            turns=[
                ToolTurn((ToolCall(RUN_CODE_TOOL_NAME, {"code": "{}['missing']"}, "first"),)),
                ToolTurn((ToolCall(RUN_CODE_TOOL_NAME, {"code": "1 + True"}, "second"),)),
                ToolTurn((ToolCall(RUN_CODE_TOOL_NAME, {"code": "1 + 1"}, "third"),)),
                "The total is 2.",
            ],
        ),
    )

    assert result.run.status == "completed"
    first, second, third = result.tool_returns(RUN_CODE_TOOL_NAME)
    assert first["outcome"] == "failed"
    assert "KeyError" in str(first["content"])
    assert "unsupported operand" in str(second["content"])
    assert third["outcome"] == "success"


async def test_gated_nested_call_suspends_without_partial_effect(
    db_session_factory: async_sessionmaker[AsyncSession],
    code_mode_scenario_tools: dict[str, Any],
) -> None:
    definition = _definition(code_mode_scenario_tools, "scenario_code_forced_write")
    seen_requests = []
    context = await build_scenario_agent(
        db_session_factory,
        tool_names=[definition.name],
    )

    result = await run_scenario(
        db_session_factory,
        context,
        model=scripted_model(
            turns=[
                ToolTurn(
                    (
                        ToolCall(
                            RUN_CODE_TOOL_NAME,
                            {
                                "code": (
                                    "try:\n"
                                    "    await scenario_code_forced_write(value='blocked')\n"
                                    "except RuntimeError as exc:\n"
                                    "    outcome = str(exc)\n"
                                    "outcome"
                                )
                            },
                            "workflow-call",
                        ),
                    )
                ),
            ],
            seen_requests=seen_requests,
        ),
    )

    assert code_mode_scenario_tools["effects"] == []
    assert result.run.status == "awaiting_approval"
    assert result.run.metadata_json["code_mode_state"]["nested_call_id"] == "workflow-call:1"
    assert len(seen_requests) == 1
    async with db_session_factory() as db:
        actor = await db.get(User, context.user_id)
        workspace = await db.get(Workspace, context.workspace_id)
        assert actor is not None and workspace is not None
        approval_state = await get_agent_run_approval_state(
            db,
            actor=actor,
            workspace=workspace,
            run_id=context.run_id,
        )
    [workflow] = approval_state.workflows
    assert workflow.outer_tool_call_id == "workflow-call"
    assert workflow.pending.tool_call_id == "workflow-call:1"
    assert approval_state.approvals[0].tool_call_id == "workflow-call:1"


async def test_batch_override_executes_and_audits_only_the_edited_rows(
    db_session_factory: async_sessionmaker[AsyncSession],
    code_mode_scenario_tools: dict[str, Any],
) -> None:
    definition = _definition(code_mode_scenario_tools, "scenario_code_batch_write")
    proposed = [
        {"text": "remove me", "match_type": "EXACT"},
        {"text": "edit me", "match_type": "PHRASE"},
    ]
    edited = [
        {"text": "edited", "match_type": "BROAD"},
        {"text": "added", "match_type": "EXACT"},
    ]
    context = await build_scenario_agent(
        db_session_factory,
        tool_names=[definition.name],
    )
    model = scripted_model(
        turns=[
            ToolTurn(
                (
                    ToolCall(
                        RUN_CODE_TOOL_NAME,
                        {"code": f"await scenario_code_batch_write(keywords={proposed!r})"},
                        "workflow-call",
                    ),
                )
            ),
            "The edited batch was applied.",
        ]
    )
    suspended = await run_scenario(db_session_factory, context, model=model)
    state = load_suspended_run_state(suspended.run)
    async with db_session_factory() as db:
        actor = await db.get(User, context.user_id)
        workspace = await db.get(Workspace, context.workspace_id)
        run = await db.get(AgentRun, context.run_id)
        membership = await db.scalar(
            select(WorkspaceMembership).where(
                WorkspaceMembership.workspace_id == context.workspace_id,
                WorkspaceMembership.user_id == context.user_id,
            )
        )
        assert actor is not None and workspace is not None and run is not None
        assert membership is not None
        deferred_results = await compile_scenario_decisions(
            db,
            actor=actor,
            workspace=workspace,
            membership=membership,
            run=run,
            decisions=[
                ScenarioDecision(
                    tool_call_id="workflow-call:1",
                    decision="approved",
                    override_args={"keywords": edited},
                )
            ],
        )

    completed = await run_scenario(
        db_session_factory,
        context,
        model=model,
        prompt=None,
        expected_status="awaiting_approval",
        message_history=state.message_history,
        deferred_tool_results=deferred_results,
    )

    assert code_mode_scenario_tools["batch_effects"] == [edited]
    nested_audits = [row for row in completed.audit_rows if row.resource_id == "workflow-call:1"]
    assert sorted(row.status for row in nested_audits) == ["pending", "success"]
    success = next(row for row in nested_audits if row.status == "success")
    validated_edited = {"keywords": [_BatchRow(**row) for row in edited]}
    validated_proposed = {"keywords": [_BatchRow(**row) for row in proposed]}
    assert success.details["args_sha256"] == digest_args(validated_edited)[0]
    assert success.details["args_sha256"] != digest_args(validated_proposed)[0]


async def test_maximum_batch_remains_one_approval_and_one_terminal_audit(
    db_session_factory: async_sessionmaker[AsyncSession],
    code_mode_scenario_tools: dict[str, Any],
) -> None:
    definition = _definition(code_mode_scenario_tools, "scenario_code_batch_write")
    rows = [{"text": f"keyword {index}", "match_type": "PHRASE"} for index in range(500)]
    context = await build_scenario_agent(
        db_session_factory,
        tool_names=[definition.name],
    )
    model = scripted_model(
        turns=[
            ToolTurn(
                (
                    ToolCall(
                        RUN_CODE_TOOL_NAME,
                        {"code": f"await scenario_code_batch_write(keywords={rows!r})"},
                        "workflow-call",
                    ),
                )
            ),
            "The maximum batch was applied.",
        ]
    )
    suspended = await run_scenario(db_session_factory, context, model=model)

    assert suspended.run.status == "awaiting_approval"
    assert code_mode_scenario_tools["batch_effects"] == []
    async with db_session_factory() as db:
        actor = await db.get(User, context.user_id)
        workspace = await db.get(Workspace, context.workspace_id)
        assert actor is not None and workspace is not None
        approval_state = await get_agent_run_approval_state(
            db, actor=actor, workspace=workspace, run_id=context.run_id
        )
    assert len(approval_state.approvals) == 1
    assert approval_state.approvals[0].args == {"keywords": rows}
    completed = await resume_code_mode_scenario(
        db_session_factory,
        context,
        suspended=suspended,
        model=model,
    )

    assert code_mode_scenario_tools["batch_effects"] == [rows]
    nested_audits = [row for row in completed.audit_rows if row.resource_id == "workflow-call:1"]
    assert sum(row.status == "pending" for row in nested_audits) == 1
    assert sum(row.status == "success" for row in nested_audits) == 1


async def test_concurrent_duplicate_nested_resume_request_starts_one_continuation(
    committed_db_session_factory: async_sessionmaker[AsyncSession],
    code_mode_scenario_tools: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    definition = _definition(code_mode_scenario_tools, "scenario_code_forced_write")
    context = await build_scenario_agent(
        committed_db_session_factory,
        tool_names=[definition.name],
    )
    await run_scenario(
        committed_db_session_factory,
        context,
        model=scripted_model(
            turns=[
                ToolTurn(
                    (
                        ToolCall(
                            RUN_CODE_TOOL_NAME,
                            {"code": "await scenario_code_forced_write(value='once')"},
                            "workflow-call",
                        ),
                    )
                )
            ]
        ),
    )
    async with committed_db_session_factory() as db:
        actor = await db.get(User, context.user_id)
        workspace = await db.get(Workspace, context.workspace_id)
    assert actor is not None and workspace is not None
    spawned = 0

    def discard_worker(_run_id, coroutine, *, sink=None, execution_control=None) -> None:
        nonlocal spawned
        del sink, execution_control
        spawned += 1
        coroutine.close()

    monkeypatch.setattr(run_task_registry, "spawn", discard_worker)
    async with committed_db_session_factory() as db:
        projection = await get_agent_run_approval_state(
            db, actor=actor, workspace=workspace, run_id=context.run_id
        )
    payload = AgentRunResumeRequest(
        approval_revision=projection.approval_revision,
        decisions=[
            AgentRunResumeDecision(
                tool_call_id="workflow-call:1",
                approval_id=projection.approvals[0].approval_id,
                decision="approved",
            )
        ],
    )

    barrier = asyncio.Barrier(2)

    async def attempt():
        await barrier.wait()
        async with committed_db_session_factory() as db:
            return await resume_agent_run_stream(
                db,
                actor=actor,
                workspace=workspace,
                run_id=context.run_id,
                payload=payload,
            )

    results = await asyncio.gather(attempt(), attempt(), return_exceptions=True)
    assert sum(isinstance(result, ConflictError) for result in results) == 1
    assert any(not isinstance(result, BaseException) for result in results)
    assert spawned == 1
    async with committed_db_session_factory() as db:
        await db.execute(delete(AgentRun).where(AgentRun.id == context.run_id))
        await db.execute(
            delete(ConversationMessage).where(
                ConversationMessage.conversation_id == context.conversation_id
            )
        )
        await db.execute(delete(Conversation).where(Conversation.id == context.conversation_id))
        await db.execute(delete(Agent).where(Agent.id == context.agent_id))
        await db.execute(
            delete(WorkspaceMembership).where(
                WorkspaceMembership.workspace_id == context.workspace_id
            )
        )
        await db.execute(delete(Workspace).where(Workspace.id == context.workspace_id))
        await db.execute(delete(User).where(User.id == context.user_id))
        await db.commit()


async def test_two_gated_writes_resume_sequentially_across_executor_restarts(
    db_session_factory: async_sessionmaker[AsyncSession],
    code_mode_scenario_tools: dict[str, Any],
) -> None:
    definition = _definition(code_mode_scenario_tools, "scenario_code_forced_write")
    context = await build_scenario_agent(
        db_session_factory,
        tool_names=[definition.name],
    )
    model = scripted_model(
        turns=[
            ToolTurn(
                (
                    ToolCall(
                        RUN_CODE_TOOL_NAME,
                        {
                            "code": (
                                "await scenario_code_forced_write(value='first')\n"
                                "await scenario_code_forced_write(value='second')\n"
                                "'done'"
                            )
                        },
                        "workflow-call",
                    ),
                )
            ),
            "Both approved writes completed.",
        ]
    )

    first = await run_scenario(db_session_factory, context, model=model)
    assert first.run.status == "awaiting_approval"
    assert code_mode_scenario_tools["effects"] == []
    await close_code_mode_executor()

    second = await resume_code_mode_scenario(
        db_session_factory,
        context,
        suspended=first,
        model=model,
    )
    assert second.run.status == "awaiting_approval"
    assert second.run.metadata_json["code_mode_state"]["nested_call_id"] == "workflow-call:2"
    assert code_mode_scenario_tools["effects"] == ["first"]
    await close_code_mode_executor()

    completed = await resume_code_mode_scenario(
        db_session_factory,
        context,
        suspended=second,
        model=model,
    )
    assert completed.run.status == "completed"
    assert code_mode_scenario_tools["effects"] == ["first", "second"]
    assert "code_mode_state" not in (completed.run.metadata_json or {})
    assert completed.output == "Both approved writes completed."


async def test_approved_write_with_invalid_evidence_requires_recovery(
    db_session_factory: async_sessionmaker[AsyncSession],
    code_mode_scenario_tools: dict[str, Any],
) -> None:
    tool_name = "scenario_code_invalid_write"
    definition = _definition(code_mode_scenario_tools, tool_name)
    context = await build_scenario_agent(
        db_session_factory,
        tool_names=[definition.name],
    )
    model = scripted_model(
        turns=[
            ToolTurn(
                (
                    ToolCall(
                        RUN_CODE_TOOL_NAME,
                        {"code": f"await {tool_name}(value='completed')"},
                        "workflow-call",
                    ),
                )
            )
        ]
    )
    suspended = await run_scenario(db_session_factory, context, model=model)

    with pytest.raises(CodeModeResumeRequiresRecoveryError):
        await resume_code_mode_scenario(
            db_session_factory,
            context,
            suspended=suspended,
            model=model,
        )

    assert code_mode_scenario_tools["effects"] == ["completed"]
    async with db_session_factory() as db:
        failed = await db.get(AgentRun, context.run_id)
        assert failed is not None
        assert failed.error_code == "code_mode_resume_requires_recovery"
        assert failed.completion_json["executed_effects"] == [
            {
                "nested_call_id": "workflow-call:1",
                "tool_name": tool_name,
                "args_sha256": digest_args({"value": "completed"})[0],
            }
        ]


async def test_snapshot_degradation_after_completed_write_fails_closed_to_recovery(
    db_session_factory: async_sessionmaker[AsyncSession],
    code_mode_scenario_tools: dict[str, Any],
) -> None:
    definition = _definition(code_mode_scenario_tools, "scenario_code_forced_write")
    context = await build_scenario_agent(
        db_session_factory,
        tool_names=[definition.name],
    )
    model = scripted_model(
        turns=[
            ToolTurn(
                (
                    ToolCall(
                        RUN_CODE_TOOL_NAME,
                        {
                            "code": (
                                "await scenario_code_forced_write(value='completed')\n"
                                "await scenario_code_forced_write(value='pending')"
                            )
                        },
                        "workflow-call",
                    ),
                )
            )
        ]
    )
    first = await run_scenario(db_session_factory, context, model=model)
    second = await resume_code_mode_scenario(
        db_session_factory,
        context,
        suspended=first,
        model=model,
    )
    assert code_mode_scenario_tools["effects"] == ["completed"]
    async with db_session_factory() as db:
        run = await db.get(AgentRun, context.run_id)
        assert run is not None
        metadata = dict(run.metadata_json or {})
        metadata["code_mode_state"] = {
            **metadata["code_mode_state"],
            "snapshot_b64": "not-valid-base64",
        }
        run.metadata_json = metadata
        await db.commit()

    with pytest.raises(CodeModeResumeRequiresRecoveryError):
        await resume_code_mode_scenario(
            db_session_factory,
            context,
            suspended=second,
            model=model,
        )

    async with db_session_factory() as db:
        failed = await db.get(AgentRun, context.run_id)
        assert failed is not None
        assert failed.status == "failed"
        assert failed.outcome == "blocked"
        assert failed.error_code == "code_mode_resume_requires_recovery"
        assert failed.completion_json["degradation_reason"] == "snapshot_corrupt"
        assert failed.completion_json["executed_effects"][0]["tool_name"] == definition.name
        assert "code_mode_state" not in (failed.metadata_json or {})


async def test_snapshot_degradation_with_read_only_prefix_returns_redraft_result(
    db_session_factory: async_sessionmaker[AsyncSession],
    code_mode_scenario_tools: dict[str, Any],
) -> None:
    definition = _definition(code_mode_scenario_tools, "scenario_code_forced_write")
    context = await build_scenario_agent(
        db_session_factory,
        tool_names=[definition.name],
    )
    seen_requests = []
    model = scripted_model(
        turns=[
            ToolTurn(
                (
                    ToolCall(
                        RUN_CODE_TOOL_NAME,
                        {"code": "await scenario_code_forced_write(value='pending')"},
                        "workflow-call",
                    ),
                )
            ),
            "I will redraft the script before trying again.",
        ],
        seen_requests=seen_requests,
    )
    suspended = await run_scenario(db_session_factory, context, model=model)
    async with db_session_factory() as db:
        run = await db.get(AgentRun, context.run_id)
        assert run is not None
        metadata = dict(run.metadata_json or {})
        metadata["code_mode_state"] = {**metadata["code_mode_state"], "monty_version": "0.0.0"}
        run.metadata_json = metadata
        await db.commit()
        actor = await db.get(User, context.user_id)
        workspace = await db.get(Workspace, context.workspace_id)
        assert actor is not None and workspace is not None
        with pytest.raises(ConflictError, match="Saved script state is invalid"):
            await get_agent_run_approval_state(
                db,
                actor=actor,
                workspace=workspace,
                run_id=context.run_id,
            )

    completed = await resume_code_mode_scenario(
        db_session_factory,
        context,
        suspended=suspended,
        model=model,
    )

    assert completed.run.status == "completed"
    assert code_mode_scenario_tools["effects"] == []
    assert "redraft the script" in str(seen_requests[1][0])
    assert "code_mode_state" not in (completed.run.metadata_json or {})


async def test_restore_failure_after_first_approved_write_requires_recovery(
    db_session_factory: async_sessionmaker[AsyncSession],
    code_mode_scenario_tools: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    definition = _definition(code_mode_scenario_tools, "scenario_code_forced_write")
    context = await build_scenario_agent(
        db_session_factory,
        tool_names=[definition.name],
    )
    model = scripted_model(
        turns=[
            ToolTurn(
                (
                    ToolCall(
                        RUN_CODE_TOOL_NAME,
                        {"code": "await scenario_code_forced_write(value='just-approved')"},
                        "workflow-call",
                    ),
                )
            )
        ]
    )
    suspended = await run_scenario(db_session_factory, context, model=model)

    async def crash_after_settlement(
        _self: MontyExecutor,
        _snapshot_bytes: bytes,
        *,
        external_lookup: Any,
        settle_pending: Any,
        timeout_seconds: float,
        prior_output: str = "",
        prior_output_truncated: bool = False,
    ) -> None:
        del external_lookup, timeout_seconds, prior_output, prior_output_truncated
        await settle_pending()
        raise TimeoutError("interpreter crashed after settlement")

    monkeypatch.setattr(MontyExecutor, "resume", crash_after_settlement)

    with pytest.raises(CodeModeResumeRequiresRecoveryError):
        await resume_code_mode_scenario(
            db_session_factory,
            context,
            suspended=suspended,
            model=model,
        )

    assert code_mode_scenario_tools["effects"] == ["just-approved"]
    async with db_session_factory() as db:
        failed = await db.get(AgentRun, context.run_id)
        assert failed is not None
        assert failed.outcome == "blocked"
        assert failed.completion_json["degradation_reason"] == "resume_crash"
        assert failed.completion_json["executed_effects"] == [
            {
                "nested_call_id": "workflow-call:1",
                "tool_name": definition.name,
                "args_sha256": digest_args({"value": "just-approved"})[0],
            }
        ]


async def test_nested_denial_resumes_script_and_audits_nested_call(
    db_session_factory: async_sessionmaker[AsyncSession],
    code_mode_scenario_tools: dict[str, Any],
) -> None:
    definition = _definition(code_mode_scenario_tools, "scenario_code_forced_write")
    context = await build_scenario_agent(
        db_session_factory,
        tool_names=[definition.name],
    )
    model = scripted_model(
        turns=[
            ToolTurn(
                (
                    ToolCall(
                        RUN_CODE_TOOL_NAME,
                        {
                            "code": (
                                "try:\n"
                                "    await scenario_code_forced_write(value='denied')\n"
                                "except PermissionError:\n"
                                "    outcome = 'alternate'\n"
                                "outcome"
                            )
                        },
                        "workflow-call",
                    ),
                )
            ),
            "The denied action was skipped.",
        ]
    )
    suspended = await run_scenario(db_session_factory, context, model=model)
    resumed = await resume_code_mode_scenario(
        db_session_factory,
        context,
        suspended=suspended,
        model=model,
        decision="denied",
        message="Operator declined",
    )

    assert resumed.run.status == "completed"
    assert code_mode_scenario_tools["effects"] == []
    nested = [row for row in resumed.audit_rows if row.resource_id == "workflow-call:1"]
    assert sorted(row.status for row in nested) == ["denied", "pending"]
    denied_audit = next(row for row in nested if row.status == "denied")
    assert denied_audit.details["outcome"] == "denied_approval"
    assert denied_audit.details["approval_ref"] == "workflow-call:1"
    assert all(
        row.resource_id != "workflow-call" or row.status != "denied" for row in resumed.audit_rows
    )


async def test_nested_write_file_staging_round_trips_and_cleans_up(
    db_session_factory: async_sessionmaker[AsyncSession],
    code_mode_local_storage: None,
) -> None:
    context = await build_scenario_agent(
        db_session_factory,
        tool_names=["write_file"],
    )
    model = scripted_model(
        turns=[
            ToolTurn(
                (
                    ToolCall(
                        RUN_CODE_TOOL_NAME,
                        {
                            "code": (
                                "try:\n"
                                "    await write_file(name='nested.md', content='nested body')\n"
                                "    outcome = 'wrote'\n"
                                "except PermissionError:\n"
                                "    outcome = 'denied'\n"
                                "outcome"
                            )
                        },
                        "workflow-call",
                    ),
                )
            ),
            "The nested file write was approved.",
        ]
    )
    suspended = await run_scenario(db_session_factory, context, model=model)
    state = load_suspended_run_state(suspended.run)
    metadata = state.deferred_tool_requests.metadata["workflow-call"]
    nested_args = metadata["nested_args"]
    assert "content" not in nested_args
    content_ref = nested_args[WRITE_FILE_CONTENT_REF_ARG]
    assert (
        await resolve_staged_write_content(
            workspace_id=context.workspace_id,
            run_id=context.run_id,
            content_ref=content_ref,
        )
        == "nested body"
    )
    [live_approval] = [
        event for event in suspended.events if event.event == "tool.approval_required"
    ]
    async with db_session_factory() as db:
        actor = await db.get(User, context.user_id)
        workspace = await db.get(Workspace, context.workspace_id)
        assert actor is not None and workspace is not None
        reloaded = await get_agent_run_approval_state(
            db,
            actor=actor,
            workspace=workspace,
            run_id=context.run_id,
        )
    assert reloaded.approvals[0].args == live_approval.data["args"]
    assert reloaded.approvals[0].args["content_bytes"] == len("nested body")
    assert reloaded.approvals[0].args["content_sha256"]

    resumed = await resume_code_mode_scenario(
        db_session_factory,
        context,
        suspended=suspended,
        model=model,
    )

    assert resumed.run.status == "completed"
    with pytest.raises(StorageNotFoundError):
        await resolve_staged_write_content(
            workspace_id=context.workspace_id,
            run_id=context.run_id,
            content_ref=content_ref,
        )
    async with db_session_factory() as db:
        stored_file = await db.scalar(
            select(File).where(
                File.workspace_id == context.workspace_id,
                File.name == "nested.md",
                File.deleted == False,  # noqa: E712
            )
        )
        assert stored_file is not None
        revision = await db.get(FileRevision, stored_file.current_revision_id)
        assert revision is not None
        content = await get_storage_provider().get_object(private_ref_from_key(revision.object_key))
    assert content == b"nested body"


async def test_hostile_intermediate_stays_framed_and_cannot_reach_write_tool(
    db_session_factory: async_sessionmaker[AsyncSession],
    code_mode_scenario_tools: dict[str, Any],
) -> None:
    seen_requests = []
    context = await build_scenario_agent(
        db_session_factory,
        tool_names=["scenario_code_hostile_read", "write_file"],
    )

    result = await run_scenario(
        db_session_factory,
        context,
        model=scripted_model(
            turns=[
                ToolTurn(
                    (
                        ToolCall(
                            RUN_CODE_TOOL_NAME,
                            {
                                "code": (
                                    "item = await scenario_code_hostile_read()\nitem['content']"
                                )
                            },
                            "workflow-call",
                        ),
                    )
                ),
                "I found an embedded instruction and did not follow it.",
            ],
            seen_requests=seen_requests,
        ),
    )

    workflow_tool = next(
        tool for tool in seen_requests[0][1].function_tools if tool.name == RUN_CODE_TOOL_NAME
    )
    assert "write_file" in workflow_tool.description
    assert code_mode_scenario_tools["effects"] == []
    assert UNTRUSTED_CONTENT_START in str(seen_requests[1][0])
    assert "code_mode_workflow" in str(seen_requests[1][0])
    assert "workflow-call" in str(seen_requests[1][0])
    assert result.output == "I found an embedded instruction and did not follow it."


async def test_scheduled_script_requires_approval_under_review_envelope(
    db_session_factory: async_sessionmaker[AsyncSession],
    code_mode_scenario_tools: dict[str, Any],
) -> None:
    definition = _definition(code_mode_scenario_tools, "scenario_code_forced_write")
    context = await build_scenario_agent(
        db_session_factory,
        tool_names=[definition.name],
        tool_policies={definition.name: TOOL_POLICY_AUTO},
        trigger="scheduled",
        metadata={"envelope": {"side_effect_policy": "require_approval"}},
    )
    turns: list[Any] = [
        ToolTurn(
            (
                ToolCall(
                    RUN_CODE_TOOL_NAME,
                    {"code": "await scenario_code_forced_write(value='scheduled')"},
                    "workflow-call",
                ),
            )
        )
    ]
    turns.append("The scheduled write completed.")
    model = scripted_model(turns=turns)

    result = await run_scenario(
        db_session_factory,
        context,
        model=model,
    )

    assert result.run.status == "awaiting_approval"
    assert code_mode_scenario_tools["effects"] == []
    result = await resume_code_mode_scenario(
        db_session_factory,
        context,
        suspended=result,
        model=model,
    )
    assert result.run.status == "completed"
    assert code_mode_scenario_tools["effects"] == ["scheduled"]


async def test_scheduled_script_enforces_deny_envelope(
    db_session_factory: async_sessionmaker[AsyncSession],
    code_mode_scenario_tools: dict[str, Any],
) -> None:
    definition = _definition(code_mode_scenario_tools, "scenario_code_forced_write")
    context = await build_scenario_agent(
        db_session_factory,
        tool_names=[definition.name],
        tool_policies={definition.name: TOOL_POLICY_AUTO},
        trigger="scheduled",
        metadata={"envelope": {"side_effect_policy": "deny"}},
    )
    result = await run_scenario(
        db_session_factory,
        context,
        model=scripted_model(
            turns=[
                ToolTurn(
                    (
                        ToolCall(
                            RUN_CODE_TOOL_NAME,
                            {
                                "code": (
                                    "try:\n"
                                    "    await scenario_code_forced_write(value='denied')\n"
                                    "except RuntimeError:\n"
                                    "    result = 'denied'\n"
                                    "result"
                                )
                            },
                            "workflow-call",
                        ),
                    )
                ),
                "The scheduled write was denied.",
            ]
        ),
    )

    assert result.run.status == "completed"
    assert code_mode_scenario_tools["effects"] == []
    nested = [row for row in result.audit_rows if row.resource_id == "workflow-call:1"]
    assert nested[-1].details["outcome"] == "denied_envelope"


async def test_tainted_scheduled_write_requires_review_even_with_allow_grant(
    db_session_factory: async_sessionmaker[AsyncSession],
    code_mode_scenario_tools: dict[str, Any],
) -> None:
    context = await build_scenario_agent(
        db_session_factory,
        tool_names=["scenario_code_hostile_read", "scenario_code_forced_write"],
        tool_policies={"scenario_code_forced_write": TOOL_POLICY_AUTO},
        trigger="scheduled",
        metadata={"envelope": {"side_effect_policy": "allow"}},
    )
    result = await run_scenario(
        db_session_factory,
        context,
        model=scripted_model(
            turns=[
                ToolTurn(
                    (
                        ToolCall(
                            RUN_CODE_TOOL_NAME,
                            {
                                "code": (
                                    "item = await scenario_code_hostile_read()\n"
                                    "await scenario_code_forced_write(value=item['content'])"
                                )
                            },
                            "workflow-call",
                        ),
                    )
                )
            ]
        ),
    )

    assert result.run.status == "awaiting_approval"
    assert code_mode_scenario_tools["effects"] == []
    approval_events = [event for event in result.events if event.event == "tool.approval_required"]
    assert approval_events[0].data["derived_from_untrusted"] is True
    assert approval_events[0].data["taint_sources"][0]["source_ref"] == "hostile_tool_result.json"
    pending_audit = next(
        row
        for row in result.audit_rows
        if row.resource_id == "workflow-call:2" and row.status == "pending"
    )
    assert pending_audit.details["derived_from_untrusted"] is True
    assert pending_audit.details["taint_sources"][0]["source_ref"] == "hostile_tool_result.json"


async def test_read_only_role_is_rechecked_inside_nested_write(
    db_session_factory: async_sessionmaker[AsyncSession],
    code_mode_scenario_tools: dict[str, Any],
) -> None:
    definition = _definition(code_mode_scenario_tools, "scenario_code_forced_write")
    context = await build_scenario_agent(
        db_session_factory,
        tool_names=[definition.name],
        tool_policies={definition.name: TOOL_POLICY_AUTO},
        role=WorkspaceRole.READ_ONLY,
    )

    result = await run_scenario(
        db_session_factory,
        context,
        model=scripted_model(
            turns=[
                ToolTurn(
                    (
                        ToolCall(
                            RUN_CODE_TOOL_NAME,
                            {
                                "code": (
                                    "try:\n"
                                    "    await scenario_code_forced_write(value='denied')\n"
                                    "except RuntimeError as exc:\n"
                                    "    outcome = str(exc)\n"
                                    "outcome"
                                )
                            },
                            "workflow-call",
                        ),
                    )
                ),
                "The workspace role denied that write.",
            ]
        ),
    )

    assert code_mode_scenario_tools["effects"] == []
    nested = [row for row in result.audit_rows if row.details.get("parent_tool_call_id")]
    assert len(nested) == 1
    assert nested[0].status == "denied"
    assert nested[0].details["error_code"] == "WorkspaceRoleDenied"
    assert result.output == "The workspace role denied that write."


def _definition(values: dict[str, Any], name: str) -> RuntimeToolDefinition:
    return next(definition for definition in values["definitions"] if definition.name == name)


async def test_google_ads_pause_then_failed_create_keeps_separate_approvals_and_evidence(
    db_session_factory,
    monkeypatch,
) -> None:
    from uuid import uuid4

    from pydantic import SecretStr

    from core.exceptions.integration import IntegrationError, IntegrationFailureDisposition
    from integrations.google_ads.tools.utils.client import google_ads_settings
    from services.integrations.context.domain import ResolvedActiveContext, ResolvedContextEntry

    selected = ResolvedContextEntry(
        integration_resource_id=uuid4(),
        provider_key="google_ads",
        resource_type="google_ads_account",
        external_id="333",
        display_name="Example account",
        connection_id=uuid4(),
        connection_label="Google Ads",
        connection_status="active",
        write_allowed=True,
        permissions_metadata={"login_customer_id": "111", "currency_code": "GBP"},
    )
    active = ResolvedActiveContext(entries=(selected,))
    monkeypatch.setattr(
        "services.agents.runtime.execute.setup.resolve_active_context",
        AsyncMock(return_value=active),
    )
    monkeypatch.setattr(
        "services.audit_events.integration_events.get_async_db_session_factory",
        lambda: db_session_factory,
    )
    monkeypatch.setattr(google_ads_settings, "GOOGLE_ADS_DEVELOPER_TOKEN", SecretStr("test-token"))
    statuses = {"20": "ENABLED", "21": "ENABLED"}
    writes = []

    def provider_rows():
        return [
            {
                "campaign": {
                    "id": "10",
                    "name": "Search",
                    "biddingStrategyType": "MANUAL_CPC",
                    "advertisingChannelType": "SEARCH",
                },
                "adGroup": {
                    "id": group,
                    "name": f"Shoes {group}",
                    "status": "ENABLED",
                    "type": "SEARCH_STANDARD",
                },
                "adGroupCriterion": {
                    "criterionId": "90",
                    "status": status,
                    "negative": False,
                    "resourceName": f"customers/333/adGroupCriteria/{group}~90",
                    "finalUrlSuffix": "src=ads",
                    "keyword": {"text": "running shoes", "matchType": "EXACT"},
                },
            }
            for group, status in statuses.items()
        ]

    async def post(path, **kwargs):
        if not path.endswith(":mutate"):
            return [{"results": provider_rows()}]
        operations = kwargs["json"]["operations"]
        kind = "pause" if "update" in operations[0] else "create"
        writes.append(kind)
        if kind == "create":
            raise IntegrationError(
                "Provider rejected the change.",
                provider_key="google_ads",
                failure_disposition=IntegrationFailureDisposition.REJECTED,
            )
        if kind == "pause":
            statuses.update(dict.fromkeys(statuses, "PAUSED"))
            return {
                "results": [{"resourceName": op["update"]["resourceName"]} for op in operations]
            }
        return {
            "results": [
                {"resourceName": f"customers/333/adGroupCriteria/{group}~91"} for group in statuses
            ]
        }

    client = type("KeywordWorkflowClient", (), {"post": staticmethod(post)})()
    for module in ("create_positive_keywords", "update_positive_keywords"):
        monkeypatch.setattr(
            f"integrations.google_ads.tools.{module}.google_ads_client",
            AsyncMock(return_value=client),
        )
    references = [
        {
            "version": 1,
            "entity_kind": "google_ads_keyword",
            "customer_id": "333",
            "campaign_id": "10",
            "ad_group_id": group,
            "criterion_id": "90",
            "text": "running shoes",
            "match_type": "EXACT",
            "status": "ENABLED",
            "final_url_suffix": "src=ads",
            "label": "running shoes",
            "scope_label": f"Search · Shoes {group}",
        }
        for group in statuses
    ]
    groups = [
        {
            "version": 1,
            "entity_kind": "google_ads_ad_group",
            "customer_id": "333",
            "campaign_id": "10",
            "ad_group_id": group,
            "label": f"Shoes {group}",
            "scope_label": "Search",
        }
        for group in statuses
    ]
    code = (
        f"paused = await google_ads_update_keywords(keywords={references!r}, patches=[{{'status': 'PAUSED'}}, {{'status': 'PAUSED'}}])\n"
        "if paused['results'][0]['data']['counts']['updated'] == 2:\n"
        f"    created = await google_ads_create_keywords(ad_groups={groups!r}, keywords=[{{'text': 'running shoes', 'match_type': 'PHRASE', 'final_url_suffix': 'src=ads'}}])\n"
        "    message = 'Replacement added; old keywords remain paused.' if created['results'][0]['data']['counts']['added'] == 2 else 'Creation failed; old keywords remain paused.'\n"
        "else:\n"
        "    message = 'Pause failed; no replacement was requested.'\n"
        "message"
    )
    context = await build_scenario_agent(
        db_session_factory,
        tool_names=["google_ads_update_keywords", "google_ads_create_keywords"],
    )
    model = scripted_model(
        turns=[
            ToolTurn((ToolCall(RUN_CODE_TOOL_NAME, {"code": code}, "keyword-workflow"),)),
            "Workflow finished.",
        ]
    )
    first = await run_scenario(db_session_factory, context, model=model)
    assert first.run.status == "awaiting_approval"
    assert writes == []
    second = await resume_code_mode_scenario(
        db_session_factory, context, suspended=first, model=model
    )
    assert second.run.status == "awaiting_approval"
    assert writes == ["pause"]
    assert set(statuses.values()) == {"PAUSED"}
    completed = await resume_code_mode_scenario(
        db_session_factory, context, suspended=second, model=model
    )
    assert completed.run.status == "completed"
    assert writes == ["pause", "create"]
    assert set(statuses.values()) == {"PAUSED"}
    transcript = json.dumps([message.parts for message in completed.messages])
    assert "Creation failed; old keywords remain paused." in transcript
    operations = [row for row in completed.audit_rows if row.details.get("provider_operation")]
    for tool_name in ("google_ads_update_keywords", "google_ads_create_keywords"):
        events = [row for row in operations if row.tool_name == tool_name]
        assert len(events) == 2
        pending = next(row for row in events if row.status == "pending")
        terminal = next(row for row in events if row.status != "pending")
        assert terminal.details["related_event_id"] == str(pending.id)
        counts = terminal.details["operation_detail"]["intent_counts"]
        failed = tool_name == "google_ads_create_keywords"
        assert counts["failed" if failed else "applied"] == 2


async def test_shared_projection_after_real_nested_suspension_and_resume(
    db_session_factory: async_sessionmaker[AsyncSession],
    code_mode_scenario_tools: dict[str, Any],
) -> None:
    definition = _definition(code_mode_scenario_tools, "scenario_code_forced_write")
    context = await build_scenario_agent(
        db_session_factory,
        tool_names=[definition.name],
    )
    model = scripted_model(
        turns=[
            ToolTurn(
                (
                    ToolCall(
                        RUN_CODE_TOOL_NAME,
                        {
                            "code": "try:\n    await scenario_code_forced_write(value='REVIEWED_VALUE')\nexcept PermissionError:\n    pass"
                        },
                        "workflow-call",
                    ),
                )
            ),
            "The workflow finished.",
        ]
    )
    suspended = await run_scenario(db_session_factory, context, model=model)
    assert suspended.run.status == "awaiting_approval"
    trace = suspended.run.metadata_json[CODE_MODE_STATE_METADATA_KEY]["nested_trace"]
    assert trace[-1]["status"] == "pending"
    assert suspended.tool_returns(RUN_CODE_TOOL_NAME) == []
    suspended_display = [
        project_shared_message(row).model_dump_json() for row in suspended.messages
    ]
    assert "REVIEWED_VALUE" not in "".join(suspended_display)
    assert "code_mode_trace" not in "".join(suspended_display)

    settled = await resume_code_mode_scenario(
        db_session_factory,
        context,
        suspended=suspended,
        model=model,
    )
    assert settled.run.status == "completed"
    children = [
        child
        for row in settled.messages
        for part in project_shared_message(row).parts["parts"]
        for child in part.get("metadata", {}).get("code_mode_trace", {}).get("calls", [])
    ]
    assert len(children) == 1
    assert children[0]["status"] == "succeeded"
    assert "args" not in children[0]
    assert "parent_tool_call_id" not in children[0]
    assert code_mode_scenario_tools["effects"] == ["REVIEWED_VALUE"]
