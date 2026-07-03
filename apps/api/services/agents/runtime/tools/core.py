# apps/api/services/agents/runtime/tools/core.py

"""Core runtime tools shipped with Praxis."""

from pydantic_ai import RunContext

from services.agents.runtime.context import RuntimeDeps
from services.agents.runtime.tools.contract import TOOL_POLICY_APPROVAL
from services.agents.runtime.tools.registry import runtime_tool


@runtime_tool(
    name="get_runtime_context",
    label="Runtime context",
    description="Read the current Praxis workspace, conversation, agent, and run identifiers.",
    takes_ctx=True,
    timeout=5,
    provider="core",
    default_policy=TOOL_POLICY_APPROVAL,
    supports_approval=True,
)
async def get_runtime_context(ctx: RunContext[RuntimeDeps]) -> dict[str, str | None]:
    """Return the current Praxis runtime context for this turn."""
    deps = ctx.deps
    return {
        "workspace_id": str(deps.run.workspace_id),
        "conversation_id": str(deps.conversation.id),
        "agent_id": str(deps.agent.id),
        "run_id": str(deps.run.id),
        "agent_name": deps.agent.name,
        "agent_slug": deps.agent.slug,
    }


@runtime_tool(
    name="add_numbers",
    label="Add numbers",
    description="Add two integers.",
    timeout=5,
    max_retries=1,
)
def add_numbers(a: int, b: int) -> int:
    """Add two integers and return the result."""
    return a + b
