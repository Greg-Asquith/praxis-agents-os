# apps/api/services/agents/runtime/delegation/build_delegation_tools.py

"""Build the runtime-owned delegation tools."""

from pydantic_ai import Tool

from services.agents.runtime.context import RuntimeDeps
from services.agents.runtime.delegation.delegate_to_agent import delegate_to_agent
from services.agents.runtime.delegation.list_delegate_agents import list_delegate_agents
from services.agents.runtime.delegation.tool_names import (
    DELEGATE_TO_AGENT_TOOL_NAME,
    LIST_DELEGATE_AGENTS_TOOL_NAME,
)
from services.agents.runtime.tools.contract import (
    TOOL_EFFECT_READ,
    TOOL_EFFECT_WRITE,
    RuntimeToolDefinition,
    ToolFieldPresentation,
    ToolPresentation,
    validate_definition,
)

LIST_DELEGATE_AGENTS_DEFINITION = RuntimeToolDefinition(
    name=LIST_DELEGATE_AGENTS_TOOL_NAME,
    function=list_delegate_agents,
    description=(
        "List the delegate agents this agent is allowed to call. "
        f"Call this before {DELEGATE_TO_AGENT_TOOL_NAME} and use the exact returned id."
    ),
    label="Find Delegate Agents",
    effect=TOOL_EFFECT_READ,
    takes_ctx=True,
    supports_approval=False,
    timeout=10,
    configurable=False,
    presentation=ToolPresentation(
        icon="bot",
        running_label="Finding Available Agents",
        completed_label="Found Available Agents",
        failed_label="Couldn't Find Available Agents",
    ),
)

DELEGATE_TO_AGENT_DEFINITION = RuntimeToolDefinition(
    name=DELEGATE_TO_AGENT_TOOL_NAME,
    function=delegate_to_agent,
    description=(
        "Run a specialized task with one listed delegate agent. "
        f"Call {LIST_DELEGATE_AGENTS_TOOL_NAME} first, choose only a clearly matching "
        "agent, and give the delegate complete instructions and context."
    ),
    label="Delegate Task",
    effect=TOOL_EFFECT_WRITE,
    takes_ctx=True,
    timeout=None,
    configurable=False,
    presentation=ToolPresentation(
        icon="bot",
        running_label="Delegating the Task",
        completed_label="Delegated the Task",
        failed_label="Couldn't Complete the Delegated Task",
        approval_title="Delegate a Task",
        approval_prompt="The agent wants to delegate this task: {task}",
        approve_label="Approve & Delegate",
        arg_fields=(
            ToolFieldPresentation(key="task", label="Task", format="multiline"),
        ),
        result_fields=(
            ToolFieldPresentation(key="output", label="Result", format="multiline"),
        ),
    ),
)

DELEGATION_TOOL_DEFINITIONS = (
    LIST_DELEGATE_AGENTS_DEFINITION,
    DELEGATE_TO_AGENT_DEFINITION,
)

for _definition in DELEGATION_TOOL_DEFINITIONS:
    validate_definition(_definition)


def build_delegation_tools() -> list[Tool[RuntimeDeps]]:
    """Return delegation tools appended by runtime policy, not agent config."""
    return [definition.to_pydantic_tool() for definition in DELEGATION_TOOL_DEFINITIONS]
