# apps/api/services/agents/runtime/capabilities.py

"""Assemble Pydantic AI capabilities for one runtime agent."""

from pydantic_ai.capabilities import AgentCapability, Hooks

from models.agent import Agent
from services.agents.runtime.context import RuntimeDeps
from services.agents.runtime.dispatch import dispatch_tool_execution


def build_runtime_capabilities(_agent: Agent) -> list[AgentCapability[RuntimeDeps]]:
    """Return capabilities attached to every runtime agent.

    Keep capability objects free of per-turn state. Hook functions receive
    ``RunContext`` and read live state from ``ctx.deps``.
    """
    hooks = Hooks(id="praxis-runtime-hooks")

    @hooks.on.tool_execute
    async def dispatch_tool(ctx, *, call, tool_def, args, handler):
        return await dispatch_tool_execution(
            ctx,
            call=call,
            tool_def=tool_def,
            args=args,
            handler=handler,
        )

    return [hooks]
