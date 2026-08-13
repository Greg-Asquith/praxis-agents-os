# apps/api/services/agents/runtime/code_mode/bridge.py

"""Bridge Monty external functions through Pydantic AI's nested-call seam."""

from __future__ import annotations

import asyncio
import json
import math
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ValidationError
from pydantic_ai import (
    ApprovalRequired,
    CallDeferred,
    ModelRetry,
    RunContext,
    ToolDenied,
    ToolFailed,
    ToolReturn,
)
from pydantic_ai.messages import BinaryContent, ToolCallPart
from pydantic_ai.tool_manager import ToolManager
from pydantic_ai.toolsets import FunctionToolset

from core.settings import settings
from services.agents.runtime.code_mode.executor import (
    MontyExecutor,
    ScriptExecution,
    get_code_mode_executor,
)
from services.agents.runtime.context import RuntimeDeps
from services.agents.runtime.events import EVENT_TOOL_CALL, EVENT_TOOL_RESULT, EVENT_WORKFLOW_STATE
from services.agents.runtime.untrusted import UntrustedContent, UntrustedNode
from utils.json_safe import json_safe_value

CODE_MODE_TRACE_METADATA_KEY = "code_mode_trace"
CODE_MODE_TAINT_SOURCE_LIMIT = 32
CODE_MODE_TRACE_EXCERPT_MAX_CHARS = 1_000


@dataclass(frozen=True)
class CodeModeBoundaryError(Exception):
    """A model-authored call failed safely at the sandbox value boundary."""

    tool_name: str
    detail: str

    def __str__(self) -> str:
        return f"{self.tool_name}: {self.detail}"


@dataclass
class _TaintState:
    sources: list[dict[str, str]] = field(default_factory=list)
    overflow: int = 0
    _seen: set[tuple[str, str]] = field(default_factory=set)

    @property
    def tainted(self) -> bool:
        return bool(self.sources) or self.overflow > 0

    def observe(self, value: Any) -> None:
        for source_kind, source_ref in _find_untrusted_sources(value):
            key = (source_kind, source_ref)
            if key in self._seen:
                continue
            self._seen.add(key)
            if len(self.sources) < CODE_MODE_TAINT_SOURCE_LIMIT:
                self.sources.append({"source_kind": source_kind, "source_ref": source_ref})
            else:
                self.overflow += 1


class CodeModeBridge:
    """Serially dispatch nested calls through the parent's prepared capability tree."""

    def __init__(
        self,
        *,
        ctx: RunContext[RuntimeDeps],
        manager: ToolManager[RuntimeDeps],
        outer_tool_call_id: str,
        max_nested_calls: int,
        value_max_bytes: int,
        result_max_bytes: int,
    ) -> None:
        self._ctx = ctx
        self._manager = manager
        self._outer_tool_call_id = outer_tool_call_id
        self._max_nested_calls = max_nested_calls
        self._value_max_bytes = value_max_bytes
        self._result_max_bytes = result_max_bytes
        self._call_count = 0
        self._lock = asyncio.Lock()
        self._taint = _TaintState()
        self._trace: list[dict[str, Any]] = []

    @classmethod
    async def create(
        cls,
        *,
        ctx: RunContext[RuntimeDeps],
        wrapped_toolset: FunctionToolset[RuntimeDeps],
        outer_tool_call_id: str,
        max_nested_calls: int | None = None,
        value_max_bytes: int | None = None,
        result_max_bytes: int | None = None,
    ) -> CodeModeBridge:
        """Prepare the framework-owned nested manager for this script execution."""
        parent_manager = ctx.tool_manager
        if parent_manager is None:
            raise RuntimeError("Code mode requires a prepared parent ToolManager")
        manager = ToolManager(
            toolset=wrapped_toolset,
            root_capability=parent_manager.root_capability,
            ctx=ctx,
            tools=await wrapped_toolset.get_tools(ctx),
            default_max_retries=parent_manager.default_max_retries,
        )
        resolved_value_max_bytes = (
            value_max_bytes
            if value_max_bytes is not None
            else settings.AGENT_CODE_MODE_VALUE_MAX_BYTES
        )
        return cls(
            ctx=ctx,
            manager=manager,
            outer_tool_call_id=outer_tool_call_id,
            max_nested_calls=(
                max_nested_calls
                if max_nested_calls is not None
                else settings.AGENT_CODE_MODE_MAX_NESTED_CALLS
            ),
            value_max_bytes=resolved_value_max_bytes,
            result_max_bytes=min(
                (
                    result_max_bytes
                    if result_max_bytes is not None
                    else settings.AGENT_CODE_MODE_RESULT_MAX_BYTES
                ),
                resolved_value_max_bytes,
            ),
        )

    def external_lookup(self) -> dict[str, Any]:
        """Expose only prepared wrapped tools as awaitable sandbox functions."""
        tools = self._manager.tools
        if tools is None:
            raise RuntimeError("Code-mode ToolManager was not prepared")
        return {name: self._external_function(name) for name in tools}

    def finalize(self, execution: ScriptExecution) -> ToolReturn:
        """Validate the outbound value and preserve sticky taint on result and output."""
        result = _normalize_boundary_value(
            execution.result,
            tool_name="run_workflow",
            max_bytes=self._result_max_bytes,
        )
        output: Any = execution.output
        if self._taint.tainted:
            result = _tainted_node(self._outer_tool_call_id, result)
            if output:
                output = _tainted_node(self._outer_tool_call_id, output)

        return_value: Any = result
        if output:
            return_value = {"output": output, "result": result}
        return ToolReturn(
            return_value=return_value,
            metadata={
                CODE_MODE_TRACE_METADATA_KEY: {
                    "tainted": self._taint.tainted,
                    "taint_sources": list(self._taint.sources),
                    "taint_sources_overflow": self._taint.overflow,
                    "output_truncated": execution.output_truncated,
                    "calls": list(self._trace),
                }
            },
        )

    def _external_function(self, tool_name: str):
        async def call(*args: Any, **kwargs: Any) -> Any:
            if args:
                raise CodeModeBoundaryError(
                    tool_name,
                    "tool arguments must be passed by keyword",
                )
            return await self._call_tool(tool_name, kwargs)

        call.__name__ = tool_name
        return call

    async def _call_tool(self, tool_name: str, args: Mapping[str, Any]) -> Any:
        async with self._lock:
            if self._call_count >= self._max_nested_calls:
                raise CodeModeBoundaryError(
                    tool_name,
                    f"nested call limit of {self._max_nested_calls} was exhausted",
                )
            self._call_count += 1
            normalized_args = _normalize_boundary_value(
                dict(args),
                tool_name=tool_name,
                max_bytes=self._value_max_bytes,
            )
            call = ToolCallPart(
                tool_name=tool_name,
                args=normalized_args,
                tool_call_id=f"{self._outer_tool_call_id}:{self._call_count}",
            )
            from services.agents.runtime.dispatch import (
                CODE_MODE_PARENT_TOOL_CALL_METADATA_KEY,
                PUBLIC_RESULT_METADATA_KEY,
                digest_args,
            )

            args_sha256, _args_bytes = digest_args(normalized_args)
            trace_entry = {
                "order": self._call_count,
                "tool_call_id": call.tool_call_id,
                "parent_tool_call_id": self._outer_tool_call_id,
                "tool_name": tool_name,
                "args_sha256": args_sha256,
                "summary": _tool_summary(tool_name),
                "status": "failed",
                "excerpt": None,
            }
            self._trace.append(trace_entry)
            await self._ctx.deps.sink.emit(
                EVENT_TOOL_CALL,
                {
                    "tool_call_id": call.tool_call_id,
                    "parent_tool_call_id": self._outer_tool_call_id,
                    "name": tool_name,
                    "args": normalized_args,
                },
            )
            try:
                result = await self._manager.handle_call(
                    call,
                    metadata={CODE_MODE_PARENT_TOOL_CALL_METADATA_KEY: self._outer_tool_call_id},
                    wrap_validation_errors=False,
                )
            except (ApprovalRequired, CallDeferred) as exc:
                error = CodeModeBoundaryError(tool_name, "tool requires approval")
                await self._record_nested_failure(trace_entry, error, status="pending")
                raise error from exc
            except (ValidationError, ModelRetry, ToolFailed) as exc:
                error = CodeModeBoundaryError(tool_name, str(exc))
                await self._record_nested_failure(trace_entry, error, status="failed")
                raise error from exc

            if isinstance(result, ToolDenied):
                error = CodeModeBoundaryError(tool_name, str(result))
                await self._record_nested_failure(trace_entry, error, status="denied")
                raise error
            has_public_result = False
            presentation_result: Any = None
            if isinstance(result, ToolReturn):
                if _has_binary_or_multimodal_content(result.content):
                    error = CodeModeBoundaryError(
                        tool_name,
                        "binary or multimodal ToolReturn content cannot enter the sandbox",
                    )
                    await self._record_nested_failure(trace_entry, error, status="failed")
                    raise error
                if (
                    isinstance(result.metadata, dict)
                    and PUBLIC_RESULT_METADATA_KEY in result.metadata
                ):
                    has_public_result = True
                    presentation_result = _to_json_value(
                        result.metadata[PUBLIC_RESULT_METADATA_KEY]
                    )
                result = result.return_value

            self._taint.observe(result)
            try:
                normalized_result = _normalize_boundary_value(
                    result,
                    tool_name=tool_name,
                    max_bytes=self._value_max_bytes,
                )
            except CodeModeBoundaryError as exc:
                await self._record_nested_failure(trace_entry, exc, status="failed")
                raise
            trace_entry["status"] = "succeeded"
            trace_entry["excerpt"] = _bounded_excerpt(normalized_result)
            # ToolReturn metadata is persisted and streamed to the application but
            # never enters model context. Keep the complete governed nested value
            # here so replay is as transparent as the live tool-result event.
            if not has_public_result:
                presentation_result = normalized_result
            trace_entry["presentation_result"] = presentation_result
            await self._ctx.deps.sink.emit(
                EVENT_TOOL_RESULT,
                {
                    "tool_call_id": call.tool_call_id,
                    "parent_tool_call_id": self._outer_tool_call_id,
                    "name": tool_name,
                    "result": presentation_result,
                },
            )
            return normalized_result

    async def _record_nested_failure(
        self,
        trace_entry: dict[str, Any],
        error: BaseException,
        *,
        status: str,
    ) -> None:
        excerpt = _bounded_excerpt(str(error))
        trace_entry["status"] = status
        trace_entry["excerpt"] = excerpt
        await self._ctx.deps.sink.emit(
            EVENT_TOOL_RESULT,
            {
                "tool_call_id": trace_entry["tool_call_id"],
                "parent_tool_call_id": self._outer_tool_call_id,
                "name": trace_entry["tool_name"],
                "result": {"status": status, "error": excerpt},
            },
        )


async def execute_code_mode_workflow(
    *,
    ctx: RunContext[RuntimeDeps],
    wrapped_toolset: FunctionToolset[RuntimeDeps],
    outer_tool_call_id: str,
    code: str,
    executor: MontyExecutor | None = None,
) -> ToolReturn:
    """Execute one tool workflow against a wrapped per-run catalog."""
    bridge = await CodeModeBridge.create(
        ctx=ctx,
        wrapped_toolset=wrapped_toolset,
        outer_tool_call_id=outer_tool_call_id,
    )
    resolved_executor = executor or await get_code_mode_executor()
    await ctx.deps.sink.emit(
        EVENT_WORKFLOW_STATE,
        {"tool_call_id": outer_tool_call_id, "state": "started"},
    )
    try:
        execution = await resolved_executor.execute(
            code,
            external_lookup=bridge.external_lookup(),
        )
        result = bridge.finalize(execution)
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        await ctx.deps.sink.emit(
            EVENT_WORKFLOW_STATE,
            {
                "tool_call_id": outer_tool_call_id,
                "state": "failed",
                "error_excerpt": _bounded_excerpt(str(exc)),
            },
        )
        raise
    await ctx.deps.sink.emit(
        EVENT_WORKFLOW_STATE,
        {
            "tool_call_id": outer_tool_call_id,
            "state": "completed",
            **({"output_excerpt": _bounded_excerpt(execution.output)} if execution.output else {}),
        },
    )
    return result


def _normalize_boundary_value(value: Any, *, tool_name: str, max_bytes: int) -> Any:
    try:
        normalized = _to_json_value(value)
        encoded = json.dumps(
            normalized,
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
        ).encode()
    except (TypeError, ValueError, RecursionError) as exc:
        raise CodeModeBoundaryError(tool_name, "value is not JSON-safe") from exc
    if len(encoded) > max_bytes:
        raise CodeModeBoundaryError(
            tool_name,
            f"value exceeds the {max_bytes}-byte sandbox value limit",
        )
    return normalized


def _to_json_value(value: Any) -> Any:
    if isinstance(value, BaseModel):
        return _to_json_value(value.model_dump(mode="json"))
    if isinstance(value, (UntrustedContent, UntrustedNode)):
        node = (
            value
            if isinstance(value, UntrustedNode)
            else UntrustedNode(
                source_kind=value.source_kind,
                source_ref=value.source_ref,
                content=value.content,
            )
        )
        return node.model_dump(mode="json")
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("non-finite numbers are not JSON-safe")
        return value
    if isinstance(value, Mapping):
        if not all(isinstance(key, str) for key in value):
            raise TypeError("JSON object keys must be strings")
        return {key: _to_json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_to_json_value(item) for item in value]
    raise TypeError(f"unsupported sandbox boundary type: {type(value).__name__}")


def _find_untrusted_sources(value: Any):
    if isinstance(value, UntrustedContent | UntrustedNode):
        yield value.source_kind, value.source_ref
        return
    if isinstance(value, BaseModel):
        yield from _find_untrusted_sources(value.model_dump(mode="python"))
        return
    if isinstance(value, Mapping):
        if value.get("node") == "praxis_untrusted":
            try:
                node = UntrustedNode.model_validate(value)
            except ValueError:
                pass
            else:
                yield node.source_kind, node.source_ref
                return
        for item in value.values():
            yield from _find_untrusted_sources(item)
    elif isinstance(value, (list, tuple)):
        for item in value:
            yield from _find_untrusted_sources(item)


def _tainted_node(tool_call_id: str, value: Any) -> UntrustedNode:
    content = (
        value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, sort_keys=True)
    )
    return UntrustedNode(
        source_kind="code_mode_workflow",
        source_ref=tool_call_id,
        content=content,
    )


def _has_binary_or_multimodal_content(content: Any) -> bool:
    if content is None or isinstance(content, str):
        return False
    return any(not isinstance(part, str) or isinstance(part, BinaryContent) for part in content)


def _tool_summary(tool_name: str) -> str:
    from services.agents.runtime.tools.registry import get_runtime_tool_definition

    definition = get_runtime_tool_definition(tool_name)
    return definition.label if definition is not None else tool_name.replace("_", " ").title()


def _bounded_excerpt(value: Any) -> str:
    safe_value = json_safe_value(value)
    if isinstance(safe_value, str):
        rendered = safe_value
    else:
        rendered = json.dumps(safe_value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    if len(rendered) <= CODE_MODE_TRACE_EXCERPT_MAX_CHARS:
        return rendered
    marker = "…[excerpt truncated]…"
    remaining = CODE_MODE_TRACE_EXCERPT_MAX_CHARS - len(marker)
    head = int(remaining * 0.8)
    return f"{rendered[:head]}{marker}{rendered[-(remaining - head) :]}"
