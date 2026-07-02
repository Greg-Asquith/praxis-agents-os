# apps/api/services/agents/runtime/delegation/build_delegation_tools.py

"""Build the runtime-owned delegation tools."""

from pydantic_ai import Tool

from services.agents.runtime.context import RuntimeDeps
from services.agents.runtime.delegation.delegate_to_agent import delegate_to_agent
from services.agents.runtime.delegation.list_delegate_agents import list_delegate_agents


def build_delegation_tools() -> list[Tool[RuntimeDeps]]:
    """Return delegation tools appended by runtime policy, not agent config."""
    return [
        Tool(
            list_delegate_agents,
            takes_ctx=True,
            name="list_delegate_agents",
            description=(
                "List the delegate agents this agent is allowed to call. "
                "Call this before delegate_to_agent and use the exact returned id."
            ),
            timeout=10,
        ),
        Tool(
            delegate_to_agent,
            takes_ctx=True,
            name="delegate_to_agent",
            description=(
                "Run a specialized task with one listed delegate agent. "
                "Call list_delegate_agents first, choose only a clearly matching agent, "
                "and give the delegate complete instructions and context."
            ),
            timeout=None,
        ),
    ]
