# apps/api/services/agents/runtime/tools/code_mode.py

"""Runtime-owned `run_workflow` registration and per-run tool factory."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import replace
from typing import Annotated

from pydantic import StringConstraints
from pydantic_ai import ModelRetry, RunContext, Tool, ToolReturn
from pydantic_ai.toolsets import FunctionToolset
from pydantic_monty import MontyError

from core.settings import settings
from services.agents.runtime.code_mode.bridge import (
    CodeModeBoundaryError,
    execute_code_mode_workflow,
)
from services.agents.runtime.context import RuntimeDeps
from services.agents.runtime.tools.contract import (
    TOOL_EFFECT_READ,
    TOOL_EFFECT_SCOPE_INTERNAL,
    TOOL_EGRESS_NONE,
    TOOL_POLICY_AUTO,
    RuntimeToolDefinition,
    ToolFieldPresentation,
    ToolPolicy,
    ToolPresentation,
)
from services.agents.runtime.tools.registry import register_tool_definition

RUN_WORKFLOW_TOOL_NAME = "run_workflow"
_REASON = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=500)]
_GUIDANCE = """Run a short Python script in a sandbox that calls your tools and processes their
results. Only the script's final value returns to you.

Choose between direct calls and a workflow with these rules:
- Call a tool directly for one call, or when you need to read a result before deciding the next step.
- Use run_workflow for three or more calls, loops over results, or filtering and aggregating data
  you do not need to read.
- Never wrap a single call in a workflow unless you are filtering/aggregating the result.
- Search for a deferred tool before using it, directly or in a workflow, so you know its arguments.
  Never guess a tool's arguments.

Write the workflow like this:
- Call a tool as an async function with its tool name, `await`, and the same keyword arguments as
  its JSON schema: `report = await tool_name(argument=value)`. A tool returns the shape its
  return schema describes.
- Leave the answer as the last expression. Return compact, decision-ready values with relevant
  counts and caveats, not raw payloads. For fan-out results, read each entry's `data`; the outer
  `results` length is the number of resources queried, not the number of rows.
- A failed call raises `RuntimeError` and a denied call raises `PermissionError`; catch them to
  report partial failures. A call that needs approval pauses the workflow until someone decides,
  then resumes where it stopped. Calls run one at a time, even under `asyncio.gather`.
- The sandbox cannot read or create files. Use `run_code`, when available, for spreadsheets,
  documents, charts, or heavy computation over file contents.
- The sandbox supports classes, dataclasses, async code, and f-strings. Allowed imports are
  asyncio, base64, binascii, collections, copy, dataclasses, datetime, functools, itertools, json,
  math, os, pathlib, random, re, sys, time, typing, and unicodedata. There is no network,
  environment, or filesystem access. `datetime.now()` reads UTC time; sleeps return immediately.
- Each workflow allows at most {max_calls} tool calls and {timeout} seconds. Keep the final value
  under {result_kb} KB of JSON; printed output is capped at {output_chars} characters.

Loaded tools you can call in a workflow: {loaded_tool_names}.
Deferred tools you can call in a workflow after you search for them: {deferred_tool_names}."""


async def _unbound_run_workflow(
    _ctx: RunContext[RuntimeDeps],
    code: str,
    reason: _REASON | None = None,
) -> ToolReturn:
    raise RuntimeError("run_workflow must be built with the run's code-eligible tools")


RUN_WORKFLOW_DEFINITION = RuntimeToolDefinition(
    name=RUN_WORKFLOW_TOOL_NAME,
    defer_loading=False,
    function=_unbound_run_workflow,
    description="Run a short sandboxed workflow that composes several of your tools.",
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
        icon="workflow",
        running_label="Running Workflow…",
        completed_label="Completed Workflow",
        failed_label="Couldn't Complete Workflow",
        arg_fields=(
            ToolFieldPresentation(key="code", label="Workflow code", format="multiline"),
            ToolFieldPresentation(key="reason", label="Reason", secondary=True),
        ),
    ),
)

register_tool_definition(RUN_WORKFLOW_DEFINITION)


def build_run_workflow_tool(
    entries: Sequence[tuple[RuntimeToolDefinition, ToolPolicy]],
) -> Tool[RuntimeDeps]:
    """Close the run's mounted code-eligible tools over one `run_workflow` tool."""
    ordered = sorted(entries, key=lambda entry: entry[0].name)
    # Nested calls resolve here, so a workflow can call a deferred tool the model has not loaded.
    workflow_toolset = FunctionToolset(
        tools=[
            definition.to_pydantic_tool(policy=policy, defer_loading=False)
            for definition, policy in ordered
        ],
        sequential=True,
    )

    async def run_workflow(
        ctx: RunContext[RuntimeDeps],
        code: str,
        reason: _REASON | None = None,
    ) -> ToolReturn:
        if ctx.tool_call_id is None:
            raise ModelRetry("The workflow call is missing its runtime identity.")
        try:
            return await execute_code_mode_workflow(
                ctx=ctx,
                wrapped_toolset=workflow_toolset,
                outer_tool_call_id=ctx.tool_call_id,
                code=code,
                reason=reason,
            )
        except (CodeModeBoundaryError, MontyError, TimeoutError) as exc:
            raise ModelRetry(f"The sandboxed workflow failed: {exc}") from exc

    definition = replace(
        RUN_WORKFLOW_DEFINITION,
        function=run_workflow,
        description=render_run_workflow_description(
            [definition for definition, _policy in ordered]
        ),
    )
    return definition.to_pydantic_tool()


def render_run_workflow_description(definitions: Sequence[RuntimeToolDefinition]) -> str:
    """Render the choice rules, sandbox limits, and callable tool names."""
    return _GUIDANCE.format(
        max_calls=settings.AGENT_CODE_MODE_MAX_NESTED_CALLS,
        timeout=f"{settings.AGENT_CODE_MODE_TIMEOUT_SECONDS:g}",
        result_kb=settings.AGENT_CODE_MODE_RESULT_MAX_BYTES // 1024,
        output_chars=f"{settings.AGENT_CODE_MODE_OUTPUT_MAX_CHARS:,}",
        loaded_tool_names=_names(definitions, deferred=False),
        deferred_tool_names=_names(definitions, deferred=True),
    )


def _names(definitions: Sequence[RuntimeToolDefinition], *, deferred: bool) -> str:
    names = [definition.name for definition in definitions if definition.defer_loading is deferred]
    return ", ".join(names) or "none"
