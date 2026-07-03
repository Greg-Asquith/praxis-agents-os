# apps/api/tests/services/agents/runtime/test_tool_registry.py

"""Unit tests for the runtime tool registry contract."""

from uuid import uuid4

import pytest

from core.exceptions.general import AppValidationError
from models.agent import Agent
from services.agents.models.domain import ModelConfigurationError
from services.agents.runtime.tools import permissions
from services.agents.runtime.tools.contract import (
    TOOL_POLICY_APPROVAL,
    TOOL_POLICY_AUTO,
    RuntimeToolDefinition,
    validate_definition,
)
from services.agents.runtime.tools.registry import (
    RUNTIME_TOOL_CATALOG,
    build_runtime_tools,
    list_allowed_tool_definitions,
    runtime_tool,
)
from services.agents.utils import validate_tool_configuration


@pytest.fixture
def cleanup_test_tools():
    before = set(RUNTIME_TOOL_CATALOG)
    yield
    for name in set(RUNTIME_TOOL_CATALOG) - before:
        RUNTIME_TOOL_CATALOG.pop(name, None)


def _noop() -> str:
    return "ok"


def _agent(
    *,
    tool_names: list[str] | None = None,
    tool_policies: dict[str, str] | None = None,
) -> Agent:
    return Agent(
        name="Tool Test Agent",
        slug=f"tool-test-agent-{uuid4().hex[:8]}",
        instructions="Use configured tools.",
        workspace_id=uuid4(),
        created_by=uuid4(),
        tool_names=tool_names or [],
        tool_policies=tool_policies,
        model_provider="openai",
        model="gpt-5.4-mini",
    )


def test_runtime_tool_decorator_registers_definition_with_derived_label(
    cleanup_test_tools,
) -> None:
    @runtime_tool(name="test_echo_value", description="Echo a value.")
    def echo_value(value: str) -> str:
        return value

    definition = RUNTIME_TOOL_CATALOG["test_echo_value"]

    assert definition.function is echo_value
    assert definition.provider == "core"
    assert definition.label == "Test echo value"
    assert definition.effect == "read"
    assert definition.allowed_policies() == frozenset(
        {TOOL_POLICY_AUTO, TOOL_POLICY_APPROVAL}
    )


def test_runtime_tool_decorator_rejects_duplicate_names(cleanup_test_tools) -> None:
    @runtime_tool(name="test_duplicate_tool", description="First registration.")
    def first_tool() -> str:
        return "first"

    with pytest.raises(RuntimeError, match="Duplicate runtime tool name"):

        @runtime_tool(name="test_duplicate_tool", description="Second registration.")
        def second_tool() -> str:
            return "second"

    assert RUNTIME_TOOL_CATALOG["test_duplicate_tool"].function is first_tool


@pytest.mark.parametrize(
    "definition",
    [
        RuntimeToolDefinition(name="BadName", function=_noop, description="Bad name."),
        RuntimeToolDefinition(name="bad_name", function=_noop, description="   "),
        RuntimeToolDefinition(
            name="bad_write",
            function=_noop,
            description="Write without approval.",
            effect="write",
            supports_approval=False,
        ),
    ],
)
def test_validate_definition_rejects_invalid_invariants(
    definition: RuntimeToolDefinition,
) -> None:
    with pytest.raises(RuntimeError):
        validate_definition(definition)


def test_allowed_policies_and_tool_build_reject_unsupported_policy() -> None:
    definition = RuntimeToolDefinition(
        name="approval_only",
        function=_noop,
        description="Requires approval.",
        default_policy=TOOL_POLICY_APPROVAL,
        supports_auto=False,
    )

    assert definition.allowed_policies() == frozenset({TOOL_POLICY_APPROVAL})

    with pytest.raises(ModelConfigurationError) as exc_info:
        definition.to_pydantic_tool(policy=TOOL_POLICY_AUTO)

    assert exc_info.value.status_code == 500
    assert exc_info.value.details["tool_name"] == "approval_only"
    assert exc_info.value.details["allowed_tool_policies"] == [TOOL_POLICY_APPROVAL]


def test_validate_tool_configuration_rejects_unsupported_tool_policy(
    cleanup_test_tools,
) -> None:
    @runtime_tool(
        name="test_approval_only",
        description="Only runs with approval.",
        default_policy=TOOL_POLICY_APPROVAL,
        supports_auto=False,
    )
    def approval_only_tool() -> str:
        return "approved"

    with pytest.raises(AppValidationError) as exc_info:
        validate_tool_configuration(
            tool_names=["test_approval_only"],
            tool_policies={"test_approval_only": TOOL_POLICY_AUTO},
        )

    assert exc_info.value.field == "tool_policies"
    assert exc_info.value.details["unsupported_tool_policies"] == {
        "test_approval_only": {
            "tool_policy": TOOL_POLICY_AUTO,
            "allowed_tool_policies": [TOOL_POLICY_APPROVAL],
        }
    }


def test_build_runtime_tools_preserves_core_tool_behavior() -> None:
    default_tools = build_runtime_tools(
        _agent(tool_names=["get_runtime_context", "add_numbers"])
    )
    approved_tools = build_runtime_tools(
        _agent(
            tool_names=["get_runtime_context", "add_numbers"],
            tool_policies={
                "get_runtime_context": TOOL_POLICY_APPROVAL,
                "add_numbers": TOOL_POLICY_APPROVAL,
            },
        )
    )

    assert [tool.name for tool in default_tools] == ["get_runtime_context", "add_numbers"]
    assert [tool.requires_approval for tool in default_tools] == [True, False]
    assert [tool.timeout for tool in default_tools] == [5, 5]
    assert [tool.max_retries for tool in default_tools] == [None, 1]
    assert [tool.requires_approval for tool in approved_tools] == [True, True]


def test_disallowed_tools_are_skipped_in_runtime_and_catalog(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def deny_add_numbers(definition: RuntimeToolDefinition, **_kwargs: object) -> bool:
        return definition.name != "add_numbers"

    monkeypatch.setattr(permissions, "is_tool_allowed", deny_add_numbers)

    tools = build_runtime_tools(_agent(tool_names=["get_runtime_context", "add_numbers"]))
    catalog = list_allowed_tool_definitions(workspace=object())

    assert [tool.name for tool in tools] == ["get_runtime_context"]
    assert "add_numbers" not in {definition.name for definition in catalog}
