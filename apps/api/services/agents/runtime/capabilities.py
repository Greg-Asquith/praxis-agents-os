# apps/api/services/agents/runtime/capabilities.py

"""Assemble Pydantic AI capabilities for one runtime agent."""

from dataclasses import replace

from pydantic_ai.capabilities import AgentCapability, Hooks, ProcessHistory
from pydantic_ai.exceptions import ModelContextWindowExceededError, RetryModelRequest

from models.agent import Agent
from services.agents.runtime.context import RuntimeDeps
from services.agents.runtime.dispatch import dispatch_tool_execution
from services.agents.runtime.execution_control import check_execution_permission
from services.agents.runtime.history import HistoryCompaction, HistoryTrimmer, history_trimmer
from services.agents.runtime.tool_search import build_tool_search_capability
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
    compaction = history_compaction or HistoryCompaction()
    trimmer = history_trimmer(
        summary=compaction.summary,
        budget=compaction.budget,
        boundary_keys=compaction.boundary_keys,
    )
    if trimmer_out is not None:
        trimmer_out.append(trimmer)

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
    async def render_untrusted_content_for_model(ctx, *, request_context, handler):
        if ctx.deps is not None:
            await check_execution_permission(ctx.deps)
        model_request = replace(
            request_context,
            messages=render_untrusted_frames(request_context.messages),
        )
        return await handler(model_request)

    @hooks.on.model_request_error
    async def tighten_history_on_overflow(ctx, *, request_context, error):
        if isinstance(error, ModelContextWindowExceededError) and trimmer.tighten_after_overflow(
            ctx.messages
        ):
            raise RetryModelRequest from error
        raise error

    @hooks.on.prepare_model_request
    async def send_tightened_history(ctx, request_context):
        # Only an overflow retry makes a second attempt. The next request records the same trim.
        if request_context.attempt == 1:
            return request_context
        return replace(
            request_context,
            messages=render_untrusted_frames(trimmer.preview(list(ctx.messages))),
        )

    return [
        hooks,
        ProcessHistory(trimmer, id="praxis-history-trimmer"),
        build_tool_search_capability(),
    ]
