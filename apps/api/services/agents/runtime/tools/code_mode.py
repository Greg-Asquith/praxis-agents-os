# apps/api/services/agents/runtime/tools/code_mode.py

"""Runtime-owned `run_workflow` registration and per-run tool factory."""

from __future__ import annotations

from dataclasses import replace
from typing import Annotated

from pydantic import StringConstraints
from pydantic_ai import ModelRetry, RunContext, Tool, ToolDefinition, ToolReturn
from pydantic_monty import MontyError

from services.agent_runs.domain import RUN_TRIGGER_INTERACTIVE
from services.agents.runtime.code_mode.bridge import (
    CodeModeBoundaryError,
    execute_code_mode_workflow,
)
from services.agents.runtime.code_mode.stubs import CodeModeCatalog
from services.agents.runtime.context import RuntimeDeps
from services.agents.runtime.tools.contract import (
    TOOL_EFFECT_READ,
    TOOL_EFFECT_SCOPE_INTERNAL,
    TOOL_EGRESS_NONE,
    TOOL_POLICY_AUTO,
    RuntimeToolDefinition,
    ToolFieldPresentation,
    ToolPresentation,
)
from services.agents.runtime.tools.registry import register_tool_definition

RUN_WORKFLOW_TOOL_NAME = "run_workflow"
_REASON = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=500)]


async def _unbound_run_workflow(
    _ctx: RunContext[RuntimeDeps],
    code: str,
    reason: _REASON | None = None,
) -> ToolReturn:
    raise RuntimeError("run_workflow must be built with a per-run code-mode catalog")


RUN_WORKFLOW_DEFINITION = RuntimeToolDefinition(
    name=RUN_WORKFLOW_TOOL_NAME,
    function=_unbound_run_workflow,
    description="Run a short sandboxed workflow that composes a collection of your available tools.",
    provider="core",
    label="Run Workflow",
    effect=TOOL_EFFECT_READ,
    effect_scope=TOOL_EFFECT_SCOPE_INTERNAL,
    egress=TOOL_EGRESS_NONE,
    code_eligible=False,
    takes_ctx=True,
    default_policy=TOOL_POLICY_AUTO,
    supports_auto=True,
    supports_approval=True,
    max_retries=1,
    configurable=False,
    auto_mount=False,
    presentation=ToolPresentation(
        icon="list-todo",
        running_label="Running Workflow",
        completed_label="Completed Workflow",
        failed_label="Workflow Failed",
        arg_fields=(
            ToolFieldPresentation(key="code", label="Workflow code", format="multiline"),
            ToolFieldPresentation(key="reason", label="Reason", secondary=True),
        ),
    ),
)

register_tool_definition(RUN_WORKFLOW_DEFINITION)


def build_run_workflow_tool(catalog: CodeModeCatalog) -> Tool[RuntimeDeps]:
    """Close one authorized catalog over the only model-visible orchestration tool."""

    async def run_workflow(
        ctx: RunContext[RuntimeDeps],
        code: str,
        reason: _REASON | None = None,
    ) -> ToolReturn:
        del reason
        if ctx.deps.run.trigger != RUN_TRIGGER_INTERACTIVE:
            raise ModelRetry("Code mode is available only in interactive conversations.")
        if ctx.tool_call_id is None:
            raise ModelRetry("The workflow call is missing its runtime identity.")
        _stamp_wrapped_catalog(ctx, catalog)
        try:
            return await execute_code_mode_workflow(
                ctx=ctx,
                wrapped_toolset=catalog.wrapped_toolset,
                outer_tool_call_id=ctx.tool_call_id,
                code=code,
            )
        except (CodeModeBoundaryError, MontyError, TimeoutError) as exc:
            raise ModelRetry(f"The sandboxed workflow failed: {exc}") from exc

    definition = replace(
        RUN_WORKFLOW_DEFINITION,
        function=run_workflow,
        description=catalog.tool_description,
    )
    tool = definition.to_pydantic_tool()
    tool.prepare = _prepare_for_interactive_run
    return tool


def _prepare_for_interactive_run(
    ctx: RunContext[RuntimeDeps],
    tool_definition: ToolDefinition,
) -> ToolDefinition | None:
    """Hide code-mode workflows from unattended principals in v1."""
    if ctx.deps.run.trigger != RUN_TRIGGER_INTERACTIVE:
        return None
    return tool_definition


def _stamp_wrapped_catalog(ctx: RunContext[RuntimeDeps], catalog: CodeModeCatalog) -> None:
    metadata = dict(ctx.deps.run.metadata_json or {})
    raw_code_mode = metadata.get("code_mode")
    code_mode = dict(raw_code_mode) if isinstance(raw_code_mode, dict) else {}
    code_mode["wrapped_tool_names"] = list(catalog.tool_names)
    metadata["code_mode"] = code_mode
    ctx.deps.run.metadata_json = metadata
