# apps/api/services/agents/runtime/tools/code_mode.py

"""Runtime-owned `run_code` registration and per-run tool factory."""

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
from services.agents.runtime.code_mode.metadata import RUN_CODE_TOOL_NAME
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

_REASON = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=500)]
_GUIDANCE = """Run a short Python script in a sandbox that calls your tools and processes their
results. Only the script's final value returns to you. This is your only way to run code.

Choose between direct calls and a script with these rules:
- Call a tool directly for one call, or when you need to read a result before deciding the next step.
- Use run_code for three or more calls, loops over results, maths, or filtering and aggregating
  data you do not need to read.
- Never wrap a single call in a script unless you are filtering/aggregating the result.
- Search for a deferred tool before using it, directly or in a script, so you know its arguments.
  Never guess a tool's arguments.

Write the script like this:
- Call a tool as an async function with its tool name, `await`, and the same keyword arguments as
  its JSON schema: `report = await tool_name(argument=value)`. A tool returns the shape its
  return schema describes.
- Leave the answer as the last expression. Return compact, decision-ready values with relevant
  counts and caveats, not raw payloads. For fan-out results, read each entry's `data`; the outer
  `results` length is the number of resources queried, not the number of rows.
- A failed call raises `RuntimeError` and a denied call raises `PermissionError`; catch them to
  report partial failures. A call that needs approval pauses the script until someone decides,
  then resumes where it stopped. Calls run one at a time, even under `asyncio.gather`.
- Work with files through tools; the sandbox has no `open()` and no file access through `os` or
  `pathlib`. `read_table` pages rows from sheets, CSV files, and saved results; `read_workbook`,
  `read_presentation`, and `read_word_document` read Office files; the `edit_*` and `create_*`
  document tools change and create them. Total rows in the script, and check each edit's
  `readback` against what you wrote.
- The sandbox supports classes, dataclasses, async code, and f-strings. Allowed imports are
  asyncio, base64, binascii, collections, copy, dataclasses, datetime, functools, itertools, json,
  math, pathlib (path strings only), random, re, sys, time, typing, and unicodedata. There is no
  network, environment, or filesystem access, and no other packages. `datetime.now()` reads UTC
  time; sleeps return immediately.
- Each script allows at most {max_calls} tool calls and {timeout} seconds. Keep the final value
  under {result_kb} KB of JSON; printed output is capped at {output_chars} characters.

Loaded tools you can call in a script: {loaded_tool_names}.
Deferred tools you can call in a script after you search for them: {deferred_tool_names}."""


async def _unbound_run_code(
    _ctx: RunContext[RuntimeDeps],
    code: str,
    reason: _REASON | None = None,
) -> ToolReturn:
    raise RuntimeError("run_code must be built with the run's code-eligible tools")


RUN_CODE_DEFINITION = RuntimeToolDefinition(
    name=RUN_CODE_TOOL_NAME,
    defer_loading=False,
    function=_unbound_run_code,
    description="Run a short sandboxed Python script that calls your tools and does the maths.",
    provider="core",
    label="Run Code",
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
        running_label="Running Script…",
        completed_label="Ran Script",
        failed_label="Couldn't Run Script",
        arg_fields=(
            ToolFieldPresentation(key="code", label="Script", format="multiline"),
            ToolFieldPresentation(key="reason", label="Reason", secondary=True),
        ),
    ),
)

register_tool_definition(RUN_CODE_DEFINITION)


def build_run_code_tool(
    entries: Sequence[tuple[RuntimeToolDefinition, ToolPolicy]],
) -> Tool[RuntimeDeps]:
    """Close the run's mounted code-eligible tools over one `run_code` tool."""
    ordered = sorted(entries, key=lambda entry: entry[0].name)
    # Nested calls resolve here, so a script can call a deferred tool the model has not loaded.
    workflow_toolset = FunctionToolset(
        tools=[
            definition.to_pydantic_tool(policy=policy, defer_loading=False)
            for definition, policy in ordered
        ],
        sequential=True,
    )

    async def run_code(
        ctx: RunContext[RuntimeDeps],
        code: str,
        reason: _REASON | None = None,
    ) -> ToolReturn:
        if ctx.tool_call_id is None:
            raise ModelRetry("The run_code call is missing its runtime identity.")
        try:
            return await execute_code_mode_workflow(
                ctx=ctx,
                wrapped_toolset=workflow_toolset,
                outer_tool_call_id=ctx.tool_call_id,
                code=code,
                reason=reason,
            )
        except (CodeModeBoundaryError, MontyError, TimeoutError) as exc:
            raise ModelRetry(f"The script failed: {exc}") from exc

    definition = replace(
        RUN_CODE_DEFINITION,
        function=run_code,
        description=render_run_code_description([definition for definition, _policy in ordered]),
    )
    return definition.to_pydantic_tool()


def render_run_code_description(definitions: Sequence[RuntimeToolDefinition]) -> str:
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
