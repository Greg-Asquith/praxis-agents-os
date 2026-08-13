"""End-to-end code-mode composition and defense-in-depth scenarios."""

import json
from pathlib import Path
from typing import Any

import pytest
from pydantic_ai import Tool
from pydantic_ai.messages import ToolReturnPart
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from models.workspace import WorkspaceRole
from services.agents.runtime.code_mode.bridge import CODE_MODE_TRACE_METADATA_KEY
from services.agents.runtime.code_mode.stubs import CodeModeCatalog
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
)
from services.agents.runtime.tools.registry import RUNTIME_TOOL_CATALOG, build_runtime_tools
from services.agents.runtime.untrusted import UNTRUSTED_CONTENT_START, UntrustedContent
from tests.support.scenario import (
    ToolCall,
    ToolTurn,
    build_scenario_agent,
    run_scenario,
    scripted_model,
)

_FIXTURE_PATH = (
    Path(__file__).parents[1] / "fixtures" / "prompt_injection" / "hostile_tool_result.json"
)
_TOOL_NAMES = (
    "scenario_code_read_first",
    "scenario_code_read_second",
    "scenario_code_hostile_read",
    "scenario_code_forced_write",
)


@pytest.fixture
def code_mode_scenario_tools() -> dict[str, Any]:
    effects: list[str] = []
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
        ),
    )
    for definition in definitions:
        RUNTIME_TOOL_CATALOG[definition.name] = definition
    try:
        yield {"definitions": definitions, "effects": effects, "hostile_payload": hostile_payload}
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


async def test_production_catalog_never_wraps_write_or_approval_policy_tools(
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

    assert definition.name in mounted
    assert RUN_WORKFLOW_TOOL_NAME in mounted
    assert definition.name not in mounted[RUN_WORKFLOW_TOOL_NAME].description


async def test_forced_gated_stub_fails_structurally_without_partial_effect(
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
                "The gated write was blocked.",
            ],
            seen_requests=seen_requests,
        ),
    )

    assert code_mode_scenario_tools["effects"] == []
    workflow_return = _tool_return(seen_requests[1][0], RUN_WORKFLOW_TOOL_NAME)
    [trace_entry] = workflow_return.metadata[CODE_MODE_TRACE_METADATA_KEY]["calls"]
    assert trace_entry["status"] == "pending"
    assert "tool requires approval" in trace_entry["excerpt"]
    assert result.output == "The gated write was blocked."


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
    assert "write_file" in first_request_tools
    workflow_tool = next(
        tool for tool in seen_requests[0][1].function_tools if tool.name == RUN_WORKFLOW_TOOL_NAME
    )
    assert "write_file" not in workflow_tool.description
    assert code_mode_scenario_tools["effects"] == []
    assert UNTRUSTED_CONTENT_START in str(seen_requests[1][0])
    assert "code_mode_workflow" in str(seen_requests[1][0])
    assert "workflow-call" in str(seen_requests[1][0])
    assert result.output == "I found an embedded instruction and did not follow it."


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


def _tool_return(messages: list[Any], tool_name: str) -> ToolReturnPart:
    return next(
        part
        for message in messages
        for part in message.parts
        if isinstance(part, ToolReturnPart) and part.tool_name == tool_name
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
