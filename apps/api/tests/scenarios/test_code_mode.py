"""End-to-end code-mode composition and defense-in-depth scenarios."""

import asyncio
import json
from collections.abc import Iterator
from pathlib import Path
from typing import Annotated, Any, Literal
from unittest.mock import AsyncMock

import pytest
from pydantic import BaseModel, Field
from pydantic_ai import DeferredToolResults, Tool, ToolApproved, ToolReturn
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from core.exceptions.general import AppValidationError, ConflictError
from core.settings import settings
from models.agent import Agent
from models.agent_run import AgentRun
from models.audit_event import AuditEvent
from models.conversation import Conversation, ConversationMessage
from models.files import File, FileRevision
from models.user import User
from models.workspace import Workspace, WorkspaceMembership, WorkspaceRole
from services.agent_runs.get_approval_state import get_agent_run_approval_state
from services.agent_runs.resume_run_stream import (
    _build_deferred_tool_results,
    resume_agent_run_stream,
)
from services.agent_runs.schemas import AgentRunResumeDecision, AgentRunResumeRequest
from services.agents.runtime.approval_state import load_suspended_run_state
from services.agents.runtime.code_mode.approval import build_code_mode_decision_metadata
from services.agents.runtime.code_mode.executor import MontyExecutor, close_code_mode_executor
from services.agents.runtime.code_mode.state import CodeModeResumeRequiresRecoveryError
from services.agents.runtime.code_mode.stubs import CodeModeCatalog
from services.agents.runtime.dispatch import digest_args
from services.agents.runtime.run_manager import run_task_registry
from services.agents.runtime.staged_tool_content import (
    WRITE_FILE_CONTENT_REF_ARG,
    resolve_staged_write_content,
)
from services.agents.runtime.tools.code_mode import (
    RUN_WORKFLOW_TOOL_NAME,
    build_run_workflow_tool,
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
from services.agents.runtime.tools.registry import RUNTIME_TOOL_CATALOG, build_runtime_tools
from services.agents.runtime.untrusted import UNTRUSTED_CONTENT_START, UntrustedContent
from services.files.utils import private_ref_from_key
from services.storage.errors import StorageNotFoundError
from services.storage.factory import get_storage_provider
from tests.support.scenario import (
    ToolCall,
    ToolTurn,
    build_scenario_agent,
    next_scenario_run,
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
    "scenario_code_oversized_public_write",
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

    async def oversized_public_write(*, value: str) -> ToolReturn[dict[str, bool]]:
        effects.append(value)
        return ToolReturn(
            return_value={"ok": True},
            metadata={"public_result": {"detail": "x" * 100}},
        )

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
            name="scenario_code_oversized_public_write",
            function=oversized_public_write,
            provider="test",
            description="Perform a write that returns oversized public evidence.",
            effect=TOOL_EFFECT_WRITE,
            effect_scope=TOOL_EFFECT_SCOPE_EXTERNAL,
            egress=TOOL_EGRESS_EXTERNAL_WRITE,
            code_eligible=True,
            default_policy=TOOL_POLICY_APPROVAL,
            configurable=False,
            max_public_result_chars=20,
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


async def test_multi_read_workflow_completes_with_nested_audits_and_replaced_schemas(
    db_session_factory: async_sessionmaker[AsyncSession],
    code_mode_scenario_tools: dict[str, Any],
) -> None:
    del code_mode_scenario_tools
    seen_requests = []
    context = await build_scenario_agent(
        db_session_factory,
        tool_names=["scenario_code_read_first", "scenario_code_read_second"],
        code_mode_enabled=True,
    )

    result = await run_scenario(
        db_session_factory,
        context,
        model=scripted_model(
            turns=[
                ToolTurn(
                    (
                        ToolCall(
                            RUN_WORKFLOW_TOOL_NAME,
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
    assert RUN_WORKFLOW_TOOL_NAME in first_request_tools
    assert "scenario_code_read_first" not in first_request_tools
    assert "scenario_code_read_second" not in first_request_tools
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


async def test_production_catalog_wraps_explicitly_eligible_write_tools(
    code_mode_scenario_tools: dict[str, Any],
) -> None:
    definition = _definition(code_mode_scenario_tools, "scenario_code_forced_write")
    agent = _agent_config(
        tool_names=[definition.name],
        tool_policies={definition.name: TOOL_POLICY_AUTO},
        code_mode_enabled=True,
    )

    tools = build_runtime_tools(agent)
    mounted = {tool.name: tool for tool in tools}

    assert definition.name not in mounted
    assert RUN_WORKFLOW_TOOL_NAME in mounted
    assert definition.name in mounted[RUN_WORKFLOW_TOOL_NAME].description


async def test_gated_stub_suspends_without_partial_effect(
    db_session_factory: async_sessionmaker[AsyncSession],
    code_mode_scenario_tools: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    definition = _definition(code_mode_scenario_tools, "scenario_code_forced_write")
    _force_only_nested_tool(monkeypatch, definition, policy=TOOL_POLICY_APPROVAL)
    seen_requests = []
    context = await build_scenario_agent(
        db_session_factory,
        tool_names=[definition.name],
        code_mode_enabled=True,
    )

    result = await run_scenario(
        db_session_factory,
        context,
        model=scripted_model(
            turns=[
                ToolTurn(
                    (
                        ToolCall(
                            RUN_WORKFLOW_TOOL_NAME,
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
    assert approval_state.workflow is not None
    assert approval_state.workflow.outer_tool_call_id == "workflow-call"
    assert approval_state.workflow.pending.tool_call_id == "workflow-call:1"
    assert approval_state.approvals[0].tool_call_id == "workflow-call:1"


async def test_nested_decision_mapping_targets_nested_id_and_validates_override(
    db_session_factory: async_sessionmaker[AsyncSession],
    code_mode_scenario_tools: dict[str, Any],
) -> None:
    definition = _definition(code_mode_scenario_tools, "scenario_code_forced_write")
    context = await build_scenario_agent(
        db_session_factory,
        tool_names=[definition.name],
        code_mode_enabled=True,
    )
    suspended = await run_scenario(
        db_session_factory,
        context,
        model=scripted_model(
            turns=[
                ToolTurn(
                    (
                        ToolCall(
                            RUN_WORKFLOW_TOOL_NAME,
                            {"code": "await scenario_code_forced_write(value='original')"},
                            "workflow-call",
                        ),
                    )
                )
            ]
        ),
    )
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
        mapped = await _build_deferred_tool_results(
            db,
            actor=actor,
            workspace=workspace,
            membership=membership,
            run=run,
            suspended_state=state,
            decisions=[
                AgentRunResumeDecision(
                    tool_call_id="workflow-call:1",
                    decision="approved",
                    override_args={"value": "overridden"},
                )
            ],
        )
        with pytest.raises(AppValidationError, match="exactly the pending approvals"):
            await _build_deferred_tool_results(
                db,
                actor=actor,
                workspace=workspace,
                membership=membership,
                run=run,
                suspended_state=state,
                decisions=[AgentRunResumeDecision(tool_call_id="stale", decision="approved")],
            )

    assert isinstance(mapped.approvals["workflow-call"], ToolApproved)
    decision = mapped.metadata["workflow-call"]["code_mode_decision"]
    assert decision["nested_tool_call_id"] == "workflow-call:1"
    assert decision["effective_args"] == {"value": "overridden"}


def test_eligible_record_batch_write_declarations_are_complete_and_faithful() -> None:
    expected = {
        "google_ads_add_ad_group_negative_keywords": ("EXACT", "PHRASE", "BROAD"),
        "google_ads_add_campaign_negative_keywords": ("EXACT", "PHRASE", "BROAD"),
        "google_ads_add_negative_keywords": ("EXACT", "PHRASE", "BROAD"),
        "google_ads_remove_ad_group_negative_keywords": (
            "EXACT",
            "PHRASE",
            "BROAD",
            "ANY",
        ),
        "google_ads_remove_campaign_negative_keywords": (
            "EXACT",
            "PHRASE",
            "BROAD",
            "ANY",
        ),
        "google_ads_remove_negative_keywords": ("EXACT", "PHRASE", "BROAD", "ANY"),
    }
    actual: dict[str, tuple[str, ...]] = {}
    for definition in RUNTIME_TOOL_CATALOG.values():
        record_fields = [
            field for field in definition.presentation.arg_fields if field.format == "records"
        ]
        if not (
            definition.code_eligible and definition.effect == TOOL_EFFECT_WRITE and record_fields
        ):
            continue
        assert len(record_fields) == 1
        field = record_fields[0]
        assert field.key == "keywords"
        assert field.editable is True
        assert field.min_rows == 1
        assert [(column.key, column.required) for column in field.columns] == [
            ("text", True),
            ("match_type", True),
        ]
        schema = definition.serialized_input_schema()
        assert schema is not None
        keywords_schema = schema["properties"]["keywords"]
        assert keywords_schema["minItems"] == 1
        assert keywords_schema["maxItems"] == 500
        actual[definition.name] = field.columns[1].options

    assert actual == expected


async def test_batch_write_suspends_once_with_every_row_in_the_approval_payload(
    db_session_factory: async_sessionmaker[AsyncSession],
    code_mode_scenario_tools: dict[str, Any],
) -> None:
    definition = _definition(code_mode_scenario_tools, "scenario_code_batch_write")
    rows = [{"text": f"keyword {index}", "match_type": "EXACT"} for index in range(1, 38)]
    context = await build_scenario_agent(
        db_session_factory,
        tool_names=[definition.name],
        code_mode_enabled=True,
    )
    suspended = await run_scenario(
        db_session_factory,
        context,
        model=scripted_model(
            turns=[
                ToolTurn(
                    (
                        ToolCall(
                            RUN_WORKFLOW_TOOL_NAME,
                            {"code": (f"await scenario_code_batch_write(keywords={rows!r})")},
                            "workflow-call",
                        ),
                    )
                )
            ]
        ),
    )

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

    assert code_mode_scenario_tools["batch_effects"] == []
    assert approval_state.workflow is not None
    assert len(approval_state.approvals) == 1
    assert approval_state.approvals[0].args == {"keywords": rows}
    pending_audits = [
        row
        for row in suspended.audit_rows
        if row.resource_id == "workflow-call:1" and row.status == "pending"
    ]
    assert len(pending_audits) == 1


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
        code_mode_enabled=True,
    )
    model = scripted_model(
        turns=[
            ToolTurn(
                (
                    ToolCall(
                        RUN_WORKFLOW_TOOL_NAME,
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
        deferred_results = await _build_deferred_tool_results(
            db,
            actor=actor,
            workspace=workspace,
            membership=membership,
            run=run,
            suspended_state=state,
            decisions=[
                AgentRunResumeDecision(
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
        code_mode_enabled=True,
    )
    model = scripted_model(
        turns=[
            ToolTurn(
                (
                    ToolCall(
                        RUN_WORKFLOW_TOOL_NAME,
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
    assert len(load_suspended_run_state(suspended.run).pending_tool_call_ids) == 1
    completed = await _resume_code_mode_scenario(
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
        code_mode_enabled=True,
    )
    await run_scenario(
        committed_db_session_factory,
        context,
        model=scripted_model(
            turns=[
                ToolTurn(
                    (
                        ToolCall(
                            RUN_WORKFLOW_TOOL_NAME,
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

    def discard_worker(_run_id, coroutine) -> None:
        nonlocal spawned
        spawned += 1
        coroutine.close()

    monkeypatch.setattr(run_task_registry, "spawn", discard_worker)
    payload = AgentRunResumeRequest(
        decisions=[AgentRunResumeDecision(tool_call_id="workflow-call:1", decision="approved")]
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


async def test_duplicate_nested_decision_after_settle_is_rejected_without_reexecution(
    db_session_factory: async_sessionmaker[AsyncSession],
    code_mode_scenario_tools: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    definition = _definition(code_mode_scenario_tools, "scenario_code_forced_write")
    context = await build_scenario_agent(
        db_session_factory,
        tool_names=[definition.name],
        code_mode_enabled=True,
    )
    model = scripted_model(
        turns=[
            ToolTurn(
                (
                    ToolCall(
                        RUN_WORKFLOW_TOOL_NAME,
                        {"code": "await scenario_code_forced_write(value='once')"},
                        "workflow-call",
                    ),
                )
            ),
            "The write completed.",
        ]
    )
    suspended = await run_scenario(db_session_factory, context, model=model)
    completed = await _resume_code_mode_scenario(
        db_session_factory,
        context,
        suspended=suspended,
        model=model,
    )
    nested_before = [
        (row.status, row.details.get("outcome"))
        for row in completed.audit_rows
        if row.resource_id == "workflow-call:1"
    ]
    resume = AsyncMock()
    monkeypatch.setattr(MontyExecutor, "resume", resume)
    async with db_session_factory() as db:
        actor = await db.get(User, context.user_id)
        workspace = await db.get(Workspace, context.workspace_id)
        assert actor is not None and workspace is not None
        with pytest.raises(ConflictError, match="not awaiting approval"):
            await resume_agent_run_stream(
                db,
                actor=actor,
                workspace=workspace,
                run_id=context.run_id,
                payload=AgentRunResumeRequest(
                    decisions=[
                        AgentRunResumeDecision(tool_call_id="workflow-call:1", decision="approved")
                    ]
                ),
            )
    async with db_session_factory() as db:
        nested_rows = list(
            await db.scalars(
                select(AuditEvent).where(
                    AuditEvent.workspace_id == context.workspace_id,
                    AuditEvent.resource_id == "workflow-call:1",
                )
            )
        )
    nested_after = [(row.status, row.details.get("outcome")) for row in nested_rows]

    assert sorted(nested_before) == sorted(nested_after)
    assert sorted(status for status, _outcome in nested_after) == ["pending", "success"]
    resume.assert_not_awaited()
    assert code_mode_scenario_tools["effects"] == ["once"]


async def test_two_gated_writes_resume_sequentially_across_executor_restarts(
    db_session_factory: async_sessionmaker[AsyncSession],
    code_mode_scenario_tools: dict[str, Any],
) -> None:
    definition = _definition(code_mode_scenario_tools, "scenario_code_forced_write")
    context = await build_scenario_agent(
        db_session_factory,
        tool_names=[definition.name],
        code_mode_enabled=True,
    )
    model = scripted_model(
        turns=[
            ToolTurn(
                (
                    ToolCall(
                        RUN_WORKFLOW_TOOL_NAME,
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

    second = await _resume_code_mode_scenario(
        db_session_factory,
        context,
        suspended=first,
        model=model,
    )
    assert second.run.status == "awaiting_approval"
    assert second.run.metadata_json["code_mode_state"]["nested_call_id"] == "workflow-call:2"
    assert code_mode_scenario_tools["effects"] == ["first"]
    await close_code_mode_executor()

    completed = await _resume_code_mode_scenario(
        db_session_factory,
        context,
        suspended=second,
        model=model,
    )
    assert completed.run.status == "completed"
    assert code_mode_scenario_tools["effects"] == ["first", "second"]
    assert "code_mode_state" not in (completed.run.metadata_json or {})
    assert completed.output == "Both approved writes completed."


@pytest.mark.parametrize(
    "tool_name",
    ["scenario_code_invalid_write", "scenario_code_oversized_public_write"],
)
async def test_approved_write_with_invalid_evidence_requires_recovery(
    db_session_factory: async_sessionmaker[AsyncSession],
    code_mode_scenario_tools: dict[str, Any],
    tool_name: str,
) -> None:
    definition = _definition(code_mode_scenario_tools, tool_name)
    context = await build_scenario_agent(
        db_session_factory,
        tool_names=[definition.name],
        code_mode_enabled=True,
    )
    model = scripted_model(
        turns=[
            ToolTurn(
                (
                    ToolCall(
                        RUN_WORKFLOW_TOOL_NAME,
                        {"code": f"await {tool_name}(value='completed')"},
                        "workflow-call",
                    ),
                )
            )
        ]
    )
    suspended = await run_scenario(db_session_factory, context, model=model)

    with pytest.raises(CodeModeResumeRequiresRecoveryError):
        await _resume_code_mode_scenario(
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


async def test_read_only_oversized_snapshot_closes_pending_audit(
    db_session_factory: async_sessionmaker[AsyncSession],
    code_mode_scenario_tools: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    definition = _definition(code_mode_scenario_tools, "scenario_code_forced_write")
    context = await build_scenario_agent(
        db_session_factory,
        tool_names=[definition.name],
        code_mode_enabled=True,
    )
    monkeypatch.setattr(settings, "AGENT_CODE_MODE_SNAPSHOT_MAX_BYTES", 1)
    result = await run_scenario(
        db_session_factory,
        context,
        model=scripted_model(
            turns=[
                ToolTurn(
                    (
                        ToolCall(
                            RUN_WORKFLOW_TOOL_NAME,
                            {"code": "await scenario_code_forced_write(value='pending')"},
                            "workflow-call",
                        ),
                    )
                ),
                "I will call the tool directly.",
            ]
        ),
    )

    assert result.run.status == "completed"
    assert code_mode_scenario_tools["effects"] == []
    assert "code_mode_state" not in (result.run.metadata_json or {})
    nested = [row for row in result.audit_rows if row.resource_id == "workflow-call:1"]
    assert sorted(row.status for row in nested) == ["failure", "pending"]
    failure = next(row for row in nested if row.status == "failure")
    assert failure.details["error_code"] == "code_mode_snapshot_too_large"


async def test_effectful_oversized_snapshot_fails_closed_with_completed_effect(
    committed_db_session_factory: async_sessionmaker[AsyncSession],
    code_mode_scenario_tools: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    completed = _definition(code_mode_scenario_tools, "scenario_code_forced_write")
    context = await build_scenario_agent(
        committed_db_session_factory,
        tool_names=[completed.name],
        code_mode_enabled=True,
    )
    model = scripted_model(
        turns=[
            ToolTurn(
                (
                    ToolCall(
                        RUN_WORKFLOW_TOOL_NAME,
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
    suspended = await run_scenario(committed_db_session_factory, context, model=model)
    monkeypatch.setattr(settings, "AGENT_CODE_MODE_STATE_MAX_BYTES", 10)
    with pytest.raises(CodeModeResumeRequiresRecoveryError) as exc_info:
        await _resume_code_mode_scenario(
            committed_db_session_factory,
            context,
            suspended=suspended,
            model=model,
        )

    assert exc_info.value.reason == "snapshot_too_large"
    assert code_mode_scenario_tools["effects"] == ["completed"]
    async with committed_db_session_factory() as db:
        failed = await db.get(AgentRun, context.run_id)
        assert failed is not None
        assert failed.status == "failed"
        assert failed.outcome == "blocked"
        assert failed.completion_json["executed_effects"][0]["tool_name"] == completed.name
        rows = list(
            await db.scalars(
                select(AuditEvent).where(
                    AuditEvent.workspace_id == context.workspace_id,
                )
            )
        )
    pending_call_rows = [
        row
        for row in rows
        if row.resource_id != exc_info.value.executed_effects[0].nested_call_id
        and row.details.get("parent_tool_call_id") == "workflow-call"
    ]
    assert sorted(row.status for row in pending_call_rows) == ["failure", "pending"]


@pytest.mark.parametrize(
    "degradation_reason",
    ["missing_key", "schema_mismatch", "monty_version_mismatch", "snapshot_corrupt"],
)
async def test_snapshot_degradation_after_completed_write_fails_closed_to_recovery(
    db_session_factory: async_sessionmaker[AsyncSession],
    code_mode_scenario_tools: dict[str, Any],
    degradation_reason: str,
) -> None:
    definition = _definition(code_mode_scenario_tools, "scenario_code_forced_write")
    context = await build_scenario_agent(
        db_session_factory,
        tool_names=[definition.name],
        code_mode_enabled=True,
    )
    model = scripted_model(
        turns=[
            ToolTurn(
                (
                    ToolCall(
                        RUN_WORKFLOW_TOOL_NAME,
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
    second = await _resume_code_mode_scenario(
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
        _degrade_code_state(metadata, degradation_reason)
        run.metadata_json = metadata
        await db.commit()

    with pytest.raises(CodeModeResumeRequiresRecoveryError):
        await _resume_code_mode_scenario(
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
        assert failed.completion_json["degradation_reason"] == degradation_reason
        assert failed.completion_json["executed_effects"][0]["tool_name"] == definition.name
        assert "code_mode_state" not in (failed.metadata_json or {})


@pytest.mark.parametrize(
    "degradation_reason",
    ["missing_key", "schema_mismatch", "monty_version_mismatch", "snapshot_corrupt"],
)
async def test_snapshot_degradation_with_read_only_prefix_returns_redraft_result(
    db_session_factory: async_sessionmaker[AsyncSession],
    code_mode_scenario_tools: dict[str, Any],
    degradation_reason: str,
) -> None:
    definition = _definition(code_mode_scenario_tools, "scenario_code_forced_write")
    context = await build_scenario_agent(
        db_session_factory,
        tool_names=[definition.name],
        code_mode_enabled=True,
    )
    seen_requests = []
    model = scripted_model(
        turns=[
            ToolTurn(
                (
                    ToolCall(
                        RUN_WORKFLOW_TOOL_NAME,
                        {"code": "await scenario_code_forced_write(value='pending')"},
                        "workflow-call",
                    ),
                )
            ),
            "I will redraft the workflow before trying again.",
        ],
        seen_requests=seen_requests,
    )
    suspended = await run_scenario(db_session_factory, context, model=model)
    async with db_session_factory() as db:
        run = await db.get(AgentRun, context.run_id)
        assert run is not None
        metadata = dict(run.metadata_json or {})
        _degrade_code_state(metadata, degradation_reason)
        run.metadata_json = metadata
        await db.commit()
        actor = await db.get(User, context.user_id)
        workspace = await db.get(Workspace, context.workspace_id)
        assert actor is not None and workspace is not None
        approval_state = await get_agent_run_approval_state(
            db,
            actor=actor,
            workspace=workspace,
            run_id=context.run_id,
        )

    assert approval_state.workflow is None
    assert approval_state.approvals[0].tool_call_id == "workflow-call:1"

    completed = await _resume_code_mode_scenario(
        db_session_factory,
        context,
        suspended=suspended,
        model=model,
    )

    assert completed.run.status == "completed"
    assert code_mode_scenario_tools["effects"] == []
    assert "redraft the workflow" in str(seen_requests[1][0])
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
        code_mode_enabled=True,
    )
    model = scripted_model(
        turns=[
            ToolTurn(
                (
                    ToolCall(
                        RUN_WORKFLOW_TOOL_NAME,
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
        await _resume_code_mode_scenario(
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


async def test_read_only_resume_crash_returns_redraft_result(
    db_session_factory: async_sessionmaker[AsyncSession],
    code_mode_scenario_tools: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    definition = _definition(code_mode_scenario_tools, "scenario_code_forced_write")
    context = await build_scenario_agent(
        db_session_factory,
        tool_names=[definition.name],
        code_mode_enabled=True,
    )
    model = scripted_model(
        turns=[
            ToolTurn(
                (
                    ToolCall(
                        RUN_WORKFLOW_TOOL_NAME,
                        {"code": "await scenario_code_forced_write(value='pending')"},
                        "workflow-call",
                    ),
                )
            ),
            "I will redraft the workflow.",
        ]
    )
    suspended = await run_scenario(db_session_factory, context, model=model)

    async def crash_before_settlement(*_args: Any, **_kwargs: Any) -> None:
        raise TimeoutError("interpreter crashed before settlement")

    monkeypatch.setattr(MontyExecutor, "resume", crash_before_settlement)
    completed = await _resume_code_mode_scenario(
        db_session_factory,
        context,
        suspended=suspended,
        model=model,
    )

    assert completed.run.status == "completed"
    assert code_mode_scenario_tools["effects"] == []
    assert completed.output == "I will redraft the workflow."


async def test_nested_denial_resumes_workflow_and_audits_nested_call(
    db_session_factory: async_sessionmaker[AsyncSession],
    code_mode_scenario_tools: dict[str, Any],
) -> None:
    definition = _definition(code_mode_scenario_tools, "scenario_code_forced_write")
    context = await build_scenario_agent(
        db_session_factory,
        tool_names=[definition.name],
        code_mode_enabled=True,
    )
    model = scripted_model(
        turns=[
            ToolTurn(
                (
                    ToolCall(
                        RUN_WORKFLOW_TOOL_NAME,
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
    resumed = await _resume_code_mode_scenario(
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


async def test_malformed_durable_trace_keeps_pending_approval_route_available(
    db_session_factory: async_sessionmaker[AsyncSession],
    code_mode_scenario_tools: dict[str, Any],
) -> None:
    definition = _definition(code_mode_scenario_tools, "scenario_code_forced_write")
    context = await build_scenario_agent(
        db_session_factory,
        tool_names=[definition.name],
        code_mode_enabled=True,
    )
    suspended = await run_scenario(
        db_session_factory,
        context,
        model=scripted_model(
            turns=[
                ToolTurn(
                    (
                        ToolCall(
                            RUN_WORKFLOW_TOOL_NAME,
                            {"code": "await scenario_code_forced_write(value='pending')"},
                            "workflow-call",
                        ),
                    )
                )
            ]
        ),
    )
    async with db_session_factory() as db:
        run = await db.get(AgentRun, context.run_id)
        actor = await db.get(User, context.user_id)
        workspace = await db.get(Workspace, context.workspace_id)
        assert run is not None and actor is not None and workspace is not None
        metadata = dict(run.metadata_json or {})
        state = dict(metadata["code_mode_state"])
        trace = [dict(item) for item in state["nested_trace"]]
        trace[0].pop("tool_call_id")
        state["nested_trace"] = trace
        metadata["code_mode_state"] = state
        run.metadata_json = metadata
        await db.flush()

        response = await get_agent_run_approval_state(
            db,
            actor=actor,
            workspace=workspace,
            run_id=context.run_id,
        )

    assert len(response.approvals) == 1
    assert response.workflow is None
    assert suspended.run.status == "awaiting_approval"


@pytest.mark.parametrize("decision", ["approved", "denied"])
async def test_nested_write_file_staging_round_trips_and_cleans_up(
    db_session_factory: async_sessionmaker[AsyncSession],
    code_mode_local_storage: None,
    decision: str,
) -> None:
    context = await build_scenario_agent(
        db_session_factory,
        tool_names=["write_file"],
        code_mode_enabled=True,
    )
    model = scripted_model(
        turns=[
            ToolTurn(
                (
                    ToolCall(
                        RUN_WORKFLOW_TOOL_NAME,
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
            f"The nested file write was {decision}.",
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

    resumed = await _resume_code_mode_scenario(
        db_session_factory,
        context,
        suspended=suspended,
        model=model,
        decision=decision,
        message="Operator declined" if decision == "denied" else None,
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
        if decision == "approved":
            assert stored_file is not None
            revision = await db.get(FileRevision, stored_file.current_revision_id)
            assert revision is not None
            content = await get_storage_provider().get_object(
                private_ref_from_key(revision.object_key)
            )
            assert content == b"nested body"
        else:
            assert stored_file is None
            nested_audits = [
                row for row in resumed.audit_rows if row.resource_id == "workflow-call:1"
            ]
            assert sorted(row.status for row in nested_audits) == ["denied", "pending"]


async def test_nested_entity_write_approves_without_edits_end_to_end(
    db_session_factory: async_sessionmaker[AsyncSession],
    code_mode_local_storage: None,
) -> None:
    context = await build_scenario_agent(
        db_session_factory,
        tool_names=["write_file"],
        code_mode_enabled=True,
    )
    create_model = scripted_model(
        turns=[
            ToolTurn(
                (
                    ToolCall(
                        RUN_WORKFLOW_TOOL_NAME,
                        {"code": "await write_file(name='entity.md', content='first')"},
                        "create-workflow",
                    ),
                )
            ),
            "The file was created.",
        ]
    )
    create_pending = await run_scenario(db_session_factory, context, model=create_model)
    await _resume_code_mode_scenario(
        db_session_factory,
        context,
        suspended=create_pending,
        model=create_model,
    )
    async with db_session_factory() as db:
        stored_file = await db.scalar(
            select(File).where(
                File.workspace_id == context.workspace_id,
                File.name == "entity.md",
                File.deleted == False,  # noqa: E712
            )
        )
        assert stored_file is not None and stored_file.current_revision_id is not None
        file_id = stored_file.id
        revision_id = stored_file.current_revision_id

    context = await next_scenario_run(db_session_factory, context)
    reference = {
        "version": 1,
        "entity_kind": "file",
        "entity_id": str(file_id),
        "label": "entity.md",
        "description": None,
        "scope_label": None,
    }
    update_model = scripted_model(
        turns=[
            ToolTurn(
                (
                    ToolCall(
                        RUN_WORKFLOW_TOOL_NAME,
                        {
                            "code": (
                                f"await write_file(name='entity.md', content='second', "
                                f"file_id={reference!r}, "
                                f"expected_current_revision_id='{revision_id}')"
                            )
                        },
                        "update-workflow",
                    ),
                )
            ),
            "The file was updated.",
        ]
    )
    update_pending = await run_scenario(db_session_factory, context, model=update_model)
    completed = await _resume_code_mode_scenario(
        db_session_factory,
        context,
        suspended=update_pending,
        model=update_model,
    )

    assert completed.run.status == "completed"
    async with db_session_factory() as db:
        stored_file = await db.get(File, file_id)
        assert stored_file is not None
        revision = await db.get(FileRevision, stored_file.current_revision_id)
        assert revision is not None
        content = await get_storage_provider().get_object(private_ref_from_key(revision.object_key))
    assert content == b"second"


async def test_hostile_intermediate_stays_framed_and_cannot_reach_write_stub(
    db_session_factory: async_sessionmaker[AsyncSession],
    code_mode_scenario_tools: dict[str, Any],
) -> None:
    seen_requests = []
    context = await build_scenario_agent(
        db_session_factory,
        tool_names=["scenario_code_hostile_read", "write_file"],
        code_mode_enabled=True,
    )

    result = await run_scenario(
        db_session_factory,
        context,
        model=scripted_model(
            turns=[
                ToolTurn(
                    (
                        ToolCall(
                            RUN_WORKFLOW_TOOL_NAME,
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

    first_request_tools = {tool.name for tool in seen_requests[0][1].function_tools}
    assert "write_file" not in first_request_tools
    workflow_tool = next(
        tool for tool in seen_requests[0][1].function_tools if tool.name == RUN_WORKFLOW_TOOL_NAME
    )
    assert "write_file" in workflow_tool.description
    assert code_mode_scenario_tools["effects"] == []
    assert UNTRUSTED_CONTENT_START in str(seen_requests[1][0])
    assert "code_mode_workflow" in str(seen_requests[1][0])
    assert "workflow-call" in str(seen_requests[1][0])
    assert result.output == "I found an embedded instruction and did not follow it."


@pytest.mark.parametrize(
    ("policy", "expected_status", "expected_effects"),
    [
        ("require_approval", "awaiting_approval", []),
        ("allow", "completed", ["scheduled"]),
    ],
)
async def test_scheduled_workflow_enforces_nested_write_envelope(
    db_session_factory: async_sessionmaker[AsyncSession],
    code_mode_scenario_tools: dict[str, Any],
    policy: str,
    expected_status: str,
    expected_effects: list[str],
) -> None:
    definition = _definition(code_mode_scenario_tools, "scenario_code_forced_write")
    context = await build_scenario_agent(
        db_session_factory,
        tool_names=[definition.name],
        tool_policies={definition.name: TOOL_POLICY_AUTO},
        code_mode_enabled=True,
        trigger="scheduled",
        metadata={"envelope": {"side_effect_policy": policy}},
    )
    turns: list[Any] = [
        ToolTurn(
            (
                ToolCall(
                    RUN_WORKFLOW_TOOL_NAME,
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

    assert result.run.status == expected_status
    assert code_mode_scenario_tools["effects"] == expected_effects
    if expected_status == "awaiting_approval":
        result = await _resume_code_mode_scenario(
            db_session_factory,
            context,
            suspended=result,
            model=model,
        )
        assert result.run.status == "completed"
        assert code_mode_scenario_tools["effects"] == ["scheduled"]


async def test_scheduled_workflow_enforces_deny_envelope(
    db_session_factory: async_sessionmaker[AsyncSession],
    code_mode_scenario_tools: dict[str, Any],
) -> None:
    definition = _definition(code_mode_scenario_tools, "scenario_code_forced_write")
    context = await build_scenario_agent(
        db_session_factory,
        tool_names=[definition.name],
        tool_policies={definition.name: TOOL_POLICY_AUTO},
        code_mode_enabled=True,
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
                            RUN_WORKFLOW_TOOL_NAME,
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
        code_mode_enabled=True,
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
                            RUN_WORKFLOW_TOOL_NAME,
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


async def test_read_only_role_is_rechecked_inside_forced_write_stub(
    db_session_factory: async_sessionmaker[AsyncSession],
    code_mode_scenario_tools: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    definition = _definition(code_mode_scenario_tools, "scenario_code_forced_write")
    _force_only_nested_tool(monkeypatch, definition, policy=TOOL_POLICY_AUTO)
    context = await build_scenario_agent(
        db_session_factory,
        tool_names=[definition.name],
        tool_policies={definition.name: TOOL_POLICY_AUTO},
        code_mode_enabled=True,
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
                            RUN_WORKFLOW_TOOL_NAME,
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


def _degrade_code_state(metadata: dict[str, Any], reason: str) -> None:
    if reason == "missing_key":
        metadata.pop("code_mode_state")
        return
    state = dict(metadata["code_mode_state"])
    if reason == "schema_mismatch":
        state["version"] = 999
    elif reason == "monty_version_mismatch":
        state["monty_version"] = "0.0.0"
    elif reason == "snapshot_corrupt":
        state["snapshot_b64"] = "not-valid-base64"
    else:  # pragma: no cover - the parameter matrix is closed above
        raise AssertionError(f"Unknown degradation reason: {reason}")
    metadata["code_mode_state"] = state


async def _resume_code_mode_scenario(
    session_factory: async_sessionmaker[AsyncSession],
    context,
    *,
    suspended,
    model,
    decision: str = "approved",
    message: str | None = None,
):
    state = load_suspended_run_state(suspended.run)
    [outer_call_id] = state.pending_tool_call_ids
    approval_metadata = state.deferred_tool_requests.metadata[outer_call_id]
    nested_args = approval_metadata["nested_args"]
    args_sha256, _args_bytes = digest_args(nested_args)
    return await run_scenario(
        session_factory,
        context,
        model=model,
        prompt=None,
        expected_status="awaiting_approval",
        message_history=state.message_history,
        deferred_tool_results=DeferredToolResults(
            approvals={outer_call_id: ToolApproved()},
            metadata={
                outer_call_id: build_code_mode_decision_metadata(
                    approval_metadata=approval_metadata,
                    decision=decision,
                    effective_args=nested_args,
                    args_sha256=args_sha256,
                    message=message,
                )
            },
        ),
    )


def _agent_config(**values: Any):
    from models.agent import Agent

    return Agent(
        name="Code Mode Catalog Scenario",
        slug="code-mode-catalog-scenario",
        model_provider="openai",
        model="gpt-5.4-mini",
        **values,
    )


def _force_only_nested_tool(
    monkeypatch: pytest.MonkeyPatch,
    definition: RuntimeToolDefinition,
    *,
    policy: str,
) -> None:
    from services.agents.runtime import loop

    original = loop.build_runtime_tools

    def forced_build(*args: Any, **kwargs: Any) -> list[Tool[Any]]:
        tools = original(*args, **kwargs)
        filtered = [
            tool for tool in tools if tool.name not in {definition.name, RUN_WORKFLOW_TOOL_NAME}
        ]
        catalog = CodeModeCatalog.build(((definition, policy),))  # type: ignore[arg-type]
        return [*filtered, build_run_workflow_tool(catalog)]

    monkeypatch.setattr(loop, "build_runtime_tools", forced_build)
