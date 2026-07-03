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


def build_delegation_tools() -> list[Tool[RuntimeDeps]]:
    """Return delegation tools appended by runtime policy, not agent config."""
    return [
        Tool(
            list_delegate_agents,
            takes_ctx=True,
            name=LIST_DELEGATE_AGENTS_TOOL_NAME,
            description=(
                "List the delegate agents this agent is allowed to call. "
                f"Call this before {DELEGATE_TO_AGENT_TOOL_NAME} and use the exact "
                "returned id."
            ),
            timeout=10,
        ),
        Tool(
            delegate_to_agent,
            takes_ctx=True,
            name=DELEGATE_TO_AGENT_TOOL_NAME,
            description=(
                "Run a specialized task with one listed delegate agent. "
                f"Call {LIST_DELEGATE_AGENTS_TOOL_NAME} first, choose only a clearly "
                "matching agent, and give the delegate complete instructions and context."
            ),
            timeout=None,
        ),
    ]
