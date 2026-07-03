# apps/api/service/agents/runtime/delegation/tool_names.py

"""Runtime-owned delegation tool names."""

LIST_DELEGATE_AGENTS_TOOL_NAME = "list_delegate_agents"
DELEGATE_TO_AGENT_TOOL_NAME = "delegate_to_agent"

DELEGATION_TOOL_NAMES = frozenset(
    {
        LIST_DELEGATE_AGENTS_TOOL_NAME,
        DELEGATE_TO_AGENT_TOOL_NAME,
    }
)
