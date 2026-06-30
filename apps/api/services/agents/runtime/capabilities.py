# apps/api/services/agents/runtime/capabilities.py

"""Assemble Pydantic AI capabilities for one runtime agent."""

import logging

from pydantic_ai.capabilities import AgentCapability, Hooks

from models.agent import Agent
from services.agents.runtime.context import RuntimeDeps

logger = logging.getLogger(__name__)


def build_runtime_capabilities(_agent: Agent) -> list[AgentCapability[RuntimeDeps]]:
    """Return capabilities attached to every runtime agent.

    Keep capability objects free of per-turn state. Hook functions receive
    ``RunContext`` and read live state from ``ctx.deps``.
    """
    hooks = Hooks(id="praxis-runtime-hooks")

    @hooks.on.before_tool_execute
    async def log_tool_start(ctx, *, call, tool_def, args):
        logger.info(
            "Agent runtime tool execution starting",
            extra={
                "run_id": str(ctx.deps.run.id),
                "conversation_id": str(ctx.deps.conversation.id),
                "agent_id": str(ctx.deps.agent.id),
                "tool_name": call.tool_name,
            },
        )
        return args

    @hooks.on.after_tool_execute
    async def log_tool_done(ctx, *, call, tool_def, args, result):
        logger.info(
            "Agent runtime tool execution completed",
            extra={
                "run_id": str(ctx.deps.run.id),
                "conversation_id": str(ctx.deps.conversation.id),
                "agent_id": str(ctx.deps.agent.id),
                "tool_name": call.tool_name,
            },
        )
        return result

    return [hooks]
