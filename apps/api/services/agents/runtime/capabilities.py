# apps/api/services/agents/runtime/capabilities.py

"""Assemble Pydantic AI capabilities for one runtime agent."""

from dataclasses import replace

from pydantic_ai.capabilities import AgentCapability, Hooks, ProcessHistory

from models.agent import Agent
from services.agents.runtime.context import RuntimeDeps
from services.agents.runtime.dispatch import dispatch_tool_execution
from services.agents.runtime.history import HistoryCompaction, HistoryTrimmer, history_trimmer
from services.agents.runtime.untrusted import render_untrusted_frames


def build_runtime_capabilities(
    _agent: Agent,
    *,
    history_compaction: HistoryCompaction | None = None,
    trimmer_out: list[HistoryTrimmer] | None = None,
) -> list[AgentCapability[RuntimeDeps]]:
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

    @hooks.on.model_request
    async def render_untrusted_content_for_model(_ctx, *, request_context, handler):
        model_request = replace(
            request_context,
            messages=render_untrusted_frames(request_context.messages),
        )
        return await handler(model_request)

    compaction = history_compaction or HistoryCompaction()
    trimmer = history_trimmer(
        summary=compaction.summary,
        token_pressure=compaction.token_pressure,
        boundary_keys=compaction.boundary_keys,
    )
    if trimmer_out is not None:
        trimmer_out.append(trimmer)

    return [
        hooks,
        ProcessHistory(trimmer, id="praxis-history-trimmer"),
    ]
