# apps/api/tests/services/agents/runtime/test_tool_registry.py

"""Unit tests for the runtime tool registry contract."""

from uuid import uuid4

import pytest

from core.exceptions.general import AppValidationError
from models.agent import Agent
from services.agents.models.domain import ModelConfigurationError
from services.agents.runtime.tools import permissions
from services.agents.runtime.tools.contract import (
    TOOL_EFFECT_WRITE,
    TOOL_KIND_CAPABILITY,
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
    assert definition.allowed_policies() == frozenset({TOOL_POLICY_AUTO, TOOL_POLICY_APPROVAL})


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
        RuntimeToolDefinition(
            name="bad_capability_function",
            function=_noop,
            description="Capability cannot carry a function.",
            kind=TOOL_KIND_CAPABILITY,
            capability_factory=lambda: object(),
        ),
        RuntimeToolDefinition(
            name="bad_capability_factory",
            function=None,
            description="Capability needs a factory.",
            kind=TOOL_KIND_CAPABILITY,
        ),
        RuntimeToolDefinition(
            name="bad_capability_write",
            function=None,
            description="Capability cannot be write effect.",
            kind=TOOL_KIND_CAPABILITY,
            effect=TOOL_EFFECT_WRITE,
            capability_factory=lambda: object(),
            supports_approval=False,
        ),
        RuntimeToolDefinition(
            name="bad_capability_approval",
            function=None,
            description="Capability cannot offer approval.",
            kind=TOOL_KIND_CAPABILITY,
            capability_factory=lambda: object(),
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


def test_capability_definition_cannot_mount_as_function_tool() -> None:
    definition = RuntimeToolDefinition(
        name="native_capability",
        function=None,
        description="Provider-native capability.",
        kind=TOOL_KIND_CAPABILITY,
        capability_factory=lambda: object(),
        supports_approval=False,
    )

    validate_definition(definition)

    with pytest.raises(ModelConfigurationError) as exc_info:
        definition.to_pydantic_tool()

    assert exc_info.value.details == {
        "tool_name": "native_capability",
        "tool_kind": TOOL_KIND_CAPABILITY,
    }


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
        _agent(tool_names=["test_runtime_context", "test_add_numbers"])
    )
    approved_tools = build_runtime_tools(
        _agent(
            tool_names=["test_runtime_context", "test_add_numbers"],
            tool_policies={
                "test_runtime_context": TOOL_POLICY_APPROVAL,
                "test_add_numbers": TOOL_POLICY_APPROVAL,
            },
        )
    )

    assert [tool.name for tool in default_tools] == [
        "list_files",
        "promote_scratch",
        "read_file",
        "read_todos",
        "write_file",
        "write_todos",
        "test_runtime_context",
        "test_add_numbers",
    ]
    assert [tool.requires_approval for tool in default_tools] == [
        False,
        True,
        False,
        False,
        False,
        False,
        True,
        False,
    ]
    assert [tool.timeout for tool in default_tools] == [10.0, 30.0, 30.0, 5, 30.0, 5, 5, 5]
    assert [tool.max_retries for tool in default_tools] == [
        None,
        None,
        None,
        None,
        None,
        None,
        None,
        1,
    ]
    assert [tool.requires_approval for tool in approved_tools] == [
        False,
        True,
        False,
        False,
        False,
        False,
        True,
        True,
    ]


def test_disallowed_tools_are_skipped_in_runtime_and_catalog(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def deny_test_add_numbers(definition: RuntimeToolDefinition, **_kwargs: object) -> bool:
        return definition.name != "test_add_numbers"

    monkeypatch.setattr(permissions, "is_tool_allowed", deny_test_add_numbers)

    tools = build_runtime_tools(_agent(tool_names=["test_runtime_context", "test_add_numbers"]))
    catalog = list_allowed_tool_definitions(workspace=object())

    assert [tool.name for tool in tools] == [
        "list_files",
        "promote_scratch",
        "read_file",
        "read_todos",
        "write_file",
        "write_todos",
        "test_runtime_context",
    ]
    assert "test_add_numbers" not in {definition.name for definition in catalog}
