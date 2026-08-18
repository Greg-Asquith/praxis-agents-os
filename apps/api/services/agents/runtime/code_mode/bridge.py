# apps/api/services/agents/runtime/code_mode/bridge.py

"""Bridge Monty external functions through Pydantic AI's nested-call seam."""

from __future__ import annotations

import asyncio
import json
import math
from collections.abc import Mapping
from dataclasses import dataclass, field
from time import monotonic
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
from services.agents.runtime.code_mode.approval import (
    CODE_MODE_DECISION_KEY,
    build_code_mode_approval_metadata,
)
from services.agents.runtime.code_mode.executor import (
    MontyExecutor,
    ScriptExecution,
    ScriptSuspension,
    get_code_mode_executor,
)
from services.agents.runtime.code_mode.state import (
    CODE_MODE_STATE_EFFECT_LIMIT,
    CODE_MODE_STATE_METADATA_KEY,
    CodeModeExecutedEffect,
    CodeModeResumeRequiresRecoveryError,
    CodeModeState,
    CodeModeStateError,
    build_code_mode_state_metadata,
    classify_snapshot_load_failure,
    clear_code_mode_state_metadata,
    load_code_mode_state,
)
from services.agents.runtime.context import RuntimeDeps
from services.agents.runtime.events import EVENT_TOOL_CALL, EVENT_TOOL_RESULT, EVENT_WORKFLOW_STATE
from services.agents.runtime.untrusted import UntrustedContent, UntrustedNode
from services.audit_events.enums import AuditStatus
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
        call_count: int = 0,
        trace: list[dict[str, Any]] | None = None,
        executed_effects: list[CodeModeExecutedEffect] | None = None,
        taint_sources: list[dict[str, str]] | None = None,
        taint_sources_overflow: int = 0,
    ) -> None:
        self._ctx = ctx
        self._manager = manager
        self._outer_tool_call_id = outer_tool_call_id
        self._max_nested_calls = max_nested_calls
        self._value_max_bytes = value_max_bytes
        self._result_max_bytes = result_max_bytes
        self._call_count = call_count
        self._lock = asyncio.Lock()
        self._taint = _TaintState()
        for source in taint_sources or ():
            self._taint.observe(
                UntrustedNode(
                    source_kind=source["source_kind"], source_ref=source["source_ref"], content=""
                )
            )
        self._taint.overflow = taint_sources_overflow
        self._trace = list(trace or ())
        self._executed_effects = list(executed_effects or ())

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
        state: CodeModeState | None = None,
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
            call_count=state.executed_call_count if state is not None else 0,
            trace=list(state.nested_trace) if state is not None else None,
            executed_effects=list(state.executed_effects) if state is not None else None,
            taint_sources=list(state.taint_sources) if state is not None else None,
            taint_sources_overflow=state.taint_sources_overflow if state is not None else 0,
        )

    @property
    def trace(self) -> list[dict[str, Any]]:
        return list(self._trace)

    @property
    def executed_effects(self) -> list[CodeModeExecutedEffect]:
        return list(self._executed_effects)

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
                CODE_MODE_DERIVED_FROM_UNTRUSTED_METADATA_KEY,
                CODE_MODE_HANDLER_STARTED_METADATA_KEY,
                CODE_MODE_PARENT_TOOL_CALL_METADATA_KEY,
                CODE_MODE_PENDING_AUDIT_RECORDED_ATTR,
                CODE_MODE_TAINT_SOURCES_METADATA_KEY,
                digest_args,
            )

            args_sha256, _args_bytes = digest_args(normalized_args)
            trace_entry = {
                "order": self._call_count,
                "tool_call_id": call.tool_call_id,
                "parent_tool_call_id": self._outer_tool_call_id,
                "tool_name": tool_name,
                "args_sha256": args_sha256,
                "summary": _tool_summary(
                    tool_name,
                    _workspace_definitions(self._ctx.deps),
                ),
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
            from services.agents.runtime.tools.contract import TOOL_EFFECT_WRITE
            from services.agents.runtime.tools.registry import resolve_runtime_tool_definition

            definition = resolve_runtime_tool_definition(
                tool_name,
                _workspace_definitions(self._ctx.deps),
            )
            if (
                self._taint.tainted
                and definition is not None
                and definition.effect == TOOL_EFFECT_WRITE
            ):
                await self._record_pending_audit(
                    call=call,
                    args=normalized_args,
                    args_sha256=args_sha256,
                    args_bytes=_args_bytes,
                    provider=definition.provider,
                )
                error = CodeModeBoundaryError(tool_name, "tool requires approval")
                await self._record_nested_failure(trace_entry, error, status="pending")
                raise ApprovalRequired(
                    metadata=build_code_mode_approval_metadata(
                        outer_tool_call_id=self._outer_tool_call_id,
                        nested_call=call,
                        reason="This action was derived from untrusted data and needs review.",
                        derived_from_untrusted=True,
                        taint_sources=list(self._taint.sources),
                    )
                )
            call_metadata = {
                CODE_MODE_PARENT_TOOL_CALL_METADATA_KEY: self._outer_tool_call_id,
                CODE_MODE_DERIVED_FROM_UNTRUSTED_METADATA_KEY: self._taint.tainted,
                CODE_MODE_TAINT_SOURCES_METADATA_KEY: list(self._taint.sources),
            }
            try:
                result = await self._manager.handle_call(
                    call,
                    metadata=call_metadata,
                    wrap_validation_errors=False,
                )
            except (ApprovalRequired, CallDeferred) as exc:
                pending_audit_recorded = (
                    isinstance(exc, ApprovalRequired)
                    and getattr(exc, CODE_MODE_PENDING_AUDIT_RECORDED_ATTR, False) is True
                )
                if not pending_audit_recorded:
                    await self._record_pending_audit(
                        call=call,
                        args=normalized_args,
                        args_sha256=args_sha256,
                        args_bytes=_args_bytes,
                        provider=definition.provider if definition is not None else "core",
                    )
                error = CodeModeBoundaryError(tool_name, "tool requires approval")
                await self._record_nested_failure(trace_entry, error, status="pending")
                raise ApprovalRequired(
                    metadata=build_code_mode_approval_metadata(
                        outer_tool_call_id=self._outer_tool_call_id,
                        nested_call=call,
                        reason="This workflow needs approval to continue.",
                        derived_from_untrusted=self._taint.tainted,
                        taint_sources=list(self._taint.sources),
                    )
                ) from exc
            except (ValidationError, ModelRetry, ToolFailed) as exc:
                if call_metadata.get(CODE_MODE_HANDLER_STARTED_METADATA_KEY) is True:
                    self._record_effect(call=call, args_sha256=args_sha256)
                error = CodeModeBoundaryError(tool_name, str(exc))
                await self._record_nested_failure(trace_entry, error, status="failed")
                raise error from exc
            except Exception:
                if call_metadata.get(CODE_MODE_HANDLER_STARTED_METADATA_KEY) is True:
                    self._record_effect(call=call, args_sha256=args_sha256)
                raise

            if isinstance(result, ToolDenied):
                error = CodeModeBoundaryError(tool_name, str(result))
                await self._record_nested_failure(trace_entry, error, status="denied")
                raise error
            try:
                normalized_result, presentation_result = self._nested_result_values(
                    tool_name=tool_name, result=result
                )
            except CodeModeBoundaryError as exc:
                self._record_effect(call=call, args_sha256=args_sha256)
                await self._record_nested_failure(trace_entry, exc, status="failed")
                raise
            trace_entry["status"] = "succeeded"
            trace_entry["excerpt"] = _bounded_excerpt(normalized_result)
            # ToolReturn metadata is persisted and streamed to the application but
            # never enters model context. Keep the complete governed nested value
            # here so replay is as transparent as the live tool-result event.
            trace_entry["presentation_result"] = presentation_result
            self._record_effect(call=call, args_sha256=args_sha256)
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

    async def settle_pending_decision(
        self,
        *,
        state: CodeModeState,
        decision_metadata: Mapping[str, Any],
    ) -> dict[str, Any]:
        """Consume one trusted nested decision and return Monty's settlement mapping."""
        raw_decision = decision_metadata.get(CODE_MODE_DECISION_KEY)
        if not isinstance(raw_decision, Mapping):
            raise CodeModeStateError("schema_mismatch", "Code Mode continuation has no decision")
        nested_call_id = raw_decision.get("nested_tool_call_id")
        effective_args = raw_decision.get("effective_args")
        args_sha256 = raw_decision.get("args_sha256")
        decision = raw_decision.get("decision")
        if (
            nested_call_id != state.nested_call_id
            or not isinstance(effective_args, Mapping)
            or not isinstance(args_sha256, str)
            or decision not in {"approved", "denied"}
        ):
            raise CodeModeStateError("schema_mismatch", "Code Mode continuation decision is stale")
        from services.agents.runtime.dispatch import (
            CODE_MODE_PARENT_TOOL_CALL_METADATA_KEY,
            digest_args,
        )

        computed_digest, _ = digest_args(dict(effective_args))
        if computed_digest != args_sha256:
            raise CodeModeStateError("schema_mismatch", "Code Mode continuation arguments changed")
        tool_name = str(decision_metadata.get("nested_tool_name") or "")
        if not tool_name:
            raise CodeModeStateError("schema_mismatch", "Code Mode continuation tool is missing")
        call = ToolCallPart(
            tool_name=tool_name,
            args=dict(effective_args),
            tool_call_id=state.nested_call_id,
        )
        if decision == "denied":
            message = raw_decision.get("message")
            self._mark_trace(
                state.nested_call_id, status="denied", result=str(message or "Denied by user")
            )
            return {"exc_type": "PermissionError", "message": str(message or "Denied by user")}

        from services.agents.runtime.dispatch import (
            CODE_MODE_DERIVED_FROM_UNTRUSTED_METADATA_KEY,
            CODE_MODE_HANDLER_STARTED_METADATA_KEY,
            CODE_MODE_TAINT_SOURCES_METADATA_KEY,
        )

        call_metadata = {
            CODE_MODE_PARENT_TOOL_CALL_METADATA_KEY: self._outer_tool_call_id,
            CODE_MODE_DERIVED_FROM_UNTRUSTED_METADATA_KEY: self._taint.tainted,
            CODE_MODE_TAINT_SOURCES_METADATA_KEY: list(self._taint.sources),
        }
        try:
            result = await self._manager.handle_call(
                call,
                approved=True,
                metadata=call_metadata,
                wrap_validation_errors=False,
            )
        except asyncio.CancelledError:
            raise
        except CodeModeStateError:
            raise
        except (ValidationError, ModelRetry, ToolFailed) as exc:
            if call_metadata.get(CODE_MODE_HANDLER_STARTED_METADATA_KEY) is True:
                self._record_effect(call=call, args_sha256=args_sha256)
            error = CodeModeBoundaryError(tool_name, str(exc))
            await self._record_nested_failure(
                self._trace_entry(state.nested_call_id), error, status="failed"
            )
            return {"exc_type": "RuntimeError", "message": str(error)}
        except Exception as exc:
            if call_metadata.get(CODE_MODE_HANDLER_STARTED_METADATA_KEY) is True:
                self._record_effect(call=call, args_sha256=args_sha256)
            error = CodeModeBoundaryError(tool_name, str(exc))
            await self._record_nested_failure(
                self._trace_entry(state.nested_call_id), error, status="failed"
            )
            return {"exc_type": "RuntimeError", "message": str(error)}
        if isinstance(result, ToolDenied):
            return {"exc_type": "PermissionError", "message": str(result)}
        try:
            normalized, presentation = self._nested_result_values(
                tool_name=tool_name, result=result
            )
        except CodeModeBoundaryError as exc:
            self._record_effect(call=call, args_sha256=args_sha256)
            await self._record_nested_failure(
                self._trace_entry(state.nested_call_id), exc, status="failed"
            )
            return {"exc_type": "RuntimeError", "message": str(exc)}
        self._mark_trace(
            state.nested_call_id,
            status="succeeded",
            result=normalized,
            presentation_result=presentation,
        )
        self._record_effect(call=call, args_sha256=args_sha256)
        await self._ctx.deps.sink.emit(
            EVENT_TOOL_RESULT,
            {
                "tool_call_id": call.tool_call_id,
                "parent_tool_call_id": self._outer_tool_call_id,
                "name": tool_name,
                "result": presentation,
            },
        )
        return {"return_value": normalized}

    def _trace_entry(self, tool_call_id: str) -> dict[str, Any]:
        for entry in reversed(self._trace):
            if entry.get("tool_call_id") == tool_call_id:
                return entry
        raise CodeModeStateError("schema_mismatch", "Code Mode nested trace entry is missing")

    async def _record_pending_audit(
        self,
        *,
        call: ToolCallPart,
        args: Mapping[str, Any],
        args_sha256: str,
        args_bytes: int,
        provider: str,
    ) -> None:
        if not hasattr(self._ctx.deps, "workspace"):
            return
        from services.agents.runtime.dispatch import record_invocation

        await record_invocation(
            deps=self._ctx.deps,
            tool_name=call.tool_name,
            tool_provider=provider,
            status=AuditStatus.PENDING,
            args=args,
            args_sha256=args_sha256,
            args_bytes=args_bytes,
            started=monotonic(),
            tool_call_id=call.tool_call_id,
            parent_tool_call_id=self._outer_tool_call_id,
            outcome="approval_requested",
            approval_ref=call.tool_call_id,
            derived_from_untrusted=self._taint.tainted,
            taint_sources=list(self._taint.sources),
        )

    def _nested_result_values(self, *, tool_name: str, result: Any) -> tuple[Any, Any]:
        from services.agents.runtime.dispatch import PUBLIC_RESULT_METADATA_KEY

        presentation_result: Any = None
        has_public_result = False
        if isinstance(result, ToolReturn):
            if _has_binary_or_multimodal_content(result.content):
                raise CodeModeBoundaryError(
                    tool_name, "binary or multimodal ToolReturn content cannot enter the sandbox"
                )
            if isinstance(result.metadata, dict) and PUBLIC_RESULT_METADATA_KEY in result.metadata:
                has_public_result = True
                presentation_result = _to_json_value(result.metadata[PUBLIC_RESULT_METADATA_KEY])
            result = result.return_value
        self._taint.observe(result)
        normalized = _normalize_boundary_value(
            result, tool_name=tool_name, max_bytes=self._value_max_bytes
        )
        return normalized, presentation_result if has_public_result else normalized

    def _mark_trace(
        self,
        tool_call_id: str,
        *,
        status: str,
        result: Any,
        presentation_result: Any | None = None,
    ) -> None:
        for entry in reversed(self._trace):
            if entry.get("tool_call_id") == tool_call_id:
                entry["status"] = status
                entry["excerpt"] = _bounded_excerpt(result)
                if status == "succeeded":
                    entry["presentation_result"] = (
                        result if presentation_result is None else presentation_result
                    )
                return

    def _record_effect(self, *, call: ToolCallPart, args_sha256: str) -> None:
        from services.agents.runtime.tools.contract import TOOL_EFFECT_WRITE
        from services.agents.runtime.tools.registry import resolve_runtime_tool_definition

        definition = resolve_runtime_tool_definition(
            call.tool_name,
            _workspace_definitions(self._ctx.deps),
        )
        if definition is not None and definition.effect == TOOL_EFFECT_WRITE:
            self._executed_effects.append(
                CodeModeExecutedEffect(call.tool_call_id, call.tool_name, args_sha256)
            )

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
    reason: str | None = None,
    executor: MontyExecutor | None = None,
) -> ToolReturn:
    """Execute one tool workflow against a wrapped per-run catalog."""
    state: CodeModeState | None = None
    decision_metadata = (
        ctx.tool_call_metadata if isinstance(ctx.tool_call_metadata, Mapping) else {}
    )
    run_metadata = getattr(ctx.deps.run, "metadata_json", None)
    raw_persisted_state = (
        run_metadata.get(CODE_MODE_STATE_METADATA_KEY)
        if isinstance(run_metadata, Mapping)
        else None
    )
    persisted_state_matches_call = (
        isinstance(raw_persisted_state, Mapping)
        and raw_persisted_state.get("outer_tool_call_id") == outer_tool_call_id
    )
    is_continuation = CODE_MODE_DECISION_KEY in decision_metadata or persisted_state_matches_call
    raw_decision = decision_metadata.get(CODE_MODE_DECISION_KEY)
    raw_state_nested_call_id = (
        raw_persisted_state.get("nested_call_id")
        if isinstance(raw_persisted_state, Mapping)
        else None
    )
    decision_matches_state = (
        not isinstance(raw_state_nested_call_id, str)
        or not raw_state_nested_call_id
        or (
            isinstance(raw_decision, Mapping)
            and raw_state_nested_call_id == raw_decision.get("nested_tool_call_id")
        )
    )
    if (
        is_continuation
        and isinstance(raw_decision, Mapping)
        and raw_decision.get("decision") == "denied"
        and decision_matches_state
    ):
        await _settle_denied_decision_evidence(
            deps=ctx.deps,
            outer_tool_call_id=outer_tool_call_id,
            decision_metadata=decision_metadata,
        )
    if is_continuation:
        try:
            state = load_code_mode_state(
                ctx.deps.run,
                outer_tool_call_id=outer_tool_call_id,
                snapshot_max_bytes=settings.AGENT_CODE_MODE_SNAPSHOT_MAX_BYTES,
            )
        except CodeModeStateError as exc:
            effects, evidence_valid = _recoverable_effects(ctx.deps.run.metadata_json)
            await _cleanup_unclaimable_approved_content(
                deps=ctx.deps,
                decision_metadata=decision_metadata,
            )
            _clear_code_mode_state(ctx.deps.run)
            if effects or not evidence_valid:
                raise CodeModeResumeRequiresRecoveryError(exc.reason, tuple(effects)) from exc
            return _redraft_result(exc.reason)
        if not isinstance(decision_metadata.get(CODE_MODE_DECISION_KEY), Mapping):
            _clear_code_mode_state(ctx.deps.run)
            if state.executed_effects:
                raise CodeModeResumeRequiresRecoveryError("schema_mismatch", state.executed_effects)
            return _redraft_result("schema_mismatch")
    bridge = await CodeModeBridge.create(
        ctx=ctx,
        wrapped_toolset=wrapped_toolset,
        outer_tool_call_id=outer_tool_call_id,
        state=state,
    )
    resolved_executor = executor or await get_code_mode_executor()
    await ctx.deps.sink.emit(
        EVENT_WORKFLOW_STATE,
        {"tool_call_id": outer_tool_call_id, "state": "started"},
    )
    try:
        started = monotonic()
        if state is None:
            execution = await resolved_executor.execute(
                code, external_lookup=bridge.external_lookup()
            )
            elapsed_seconds = monotonic() - started
        else:
            remaining = max(
                0.001,
                settings.AGENT_CODE_MODE_TIMEOUT_SECONDS - state.consumed_budget.elapsed_seconds,
            )

            async def settle_pending() -> dict[str, Any]:
                # Label operational failures during settlement as resume crashes, not corrupt snapshots.
                try:
                    return await bridge.settle_pending_decision(
                        state=state,
                        decision_metadata=decision_metadata,
                    )
                except (asyncio.CancelledError, CodeModeStateError):
                    raise
                except Exception as exc:
                    raise CodeModeStateError(
                        "resume_crash",
                        f"Code Mode settlement failed after restore: {type(exc).__name__}",
                    ) from exc

            try:
                execution = await resolved_executor.resume(
                    state.snapshot,
                    external_lookup=bridge.external_lookup(),
                    settle_pending=settle_pending,
                    timeout_seconds=remaining,
                    prior_output=state.output,
                    prior_output_truncated=state.output_truncated,
                )
            except Exception as exc:
                failure = (
                    exc
                    if isinstance(exc, CodeModeStateError)
                    else classify_snapshot_load_failure(exc)
                )
                await _cleanup_unclaimable_approved_content(
                    deps=ctx.deps,
                    decision_metadata=decision_metadata,
                )
                _clear_code_mode_state(ctx.deps.run)
                completed_effects = tuple(bridge.executed_effects)
                if completed_effects:
                    raise CodeModeResumeRequiresRecoveryError(
                        failure.reason,
                        completed_effects,
                    ) from exc
                return _redraft_result(failure.reason)
            elapsed_seconds = state.consumed_budget.elapsed_seconds + monotonic() - started
            if isinstance(execution, ScriptExecution):
                _clear_code_mode_state(ctx.deps.run)
        if isinstance(execution, ScriptSuspension):
            # One durable suspension per run: refuse to overwrite another workflow's snapshot.
            current_metadata = getattr(ctx.deps.run, "metadata_json", None)
            existing_state = (
                current_metadata.get(CODE_MODE_STATE_METADATA_KEY)
                if isinstance(current_metadata, Mapping)
                else None
            )
            if (
                isinstance(existing_state, Mapping)
                and existing_state.get("outer_tool_call_id") != outer_tool_call_id
            ):
                return ToolReturn(
                    return_value={
                        "status": "failed",
                        "error": (
                            "Another workflow is already paused for approval in this run. "
                            "Retry after that decision, or call the tool directly."
                        ),
                    }
                )
            raw_approval_metadata = execution.approval.metadata
            if not isinstance(raw_approval_metadata, dict):
                raise CodeModeBoundaryError("run_workflow", "nested approval metadata is invalid")
            approval_metadata = {
                **raw_approval_metadata,
                "executed_effects": [effect.__dict__ for effect in bridge.executed_effects],
            }
            nested_call_id = str(approval_metadata.get("nested_tool_call_id") or "")
            try:
                ctx.deps.run.metadata_json = build_code_mode_state_metadata(
                    run=ctx.deps.run,
                    outer_tool_call_id=outer_tool_call_id,
                    nested_call_id=nested_call_id,
                    code=code,
                    reason=reason,
                    snapshot=execution.snapshot,
                    executed_call_count=bridge._call_count,
                    elapsed_seconds=elapsed_seconds,
                    executed_effects=[effect.__dict__ for effect in bridge.executed_effects],
                    nested_trace=bridge.trace,
                    tainted=bridge._taint.tainted,
                    taint_sources=bridge._taint.sources,
                    taint_sources_overflow=bridge._taint.overflow,
                    output=execution.output,
                    output_truncated=execution.output_truncated,
                    snapshot_max_bytes=settings.AGENT_CODE_MODE_SNAPSHOT_MAX_BYTES,
                    state_max_bytes=settings.AGENT_CODE_MODE_STATE_MAX_BYTES,
                )
            except CodeModeStateError as exc:
                _clear_code_mode_state(ctx.deps.run)
                await _record_failed_suspension_audit(
                    deps=ctx.deps,
                    outer_tool_call_id=outer_tool_call_id,
                    approval_metadata=approval_metadata,
                )
                if bridge.executed_effects:
                    raise CodeModeResumeRequiresRecoveryError(
                        exc.reason,
                        tuple(bridge.executed_effects),
                    ) from exc
                return ToolReturn(
                    return_value={
                        "status": "failed",
                        "error": "The workflow result was too large to pause on. Call the tool directly.",
                    }
                )
            raise ApprovalRequired(metadata=approval_metadata)
        result = bridge.finalize(execution)
    except asyncio.CancelledError:
        raise
    except ApprovalRequired:
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


async def _settle_denied_decision_evidence(
    *,
    deps: RuntimeDeps,
    outer_tool_call_id: str,
    decision_metadata: Mapping[str, Any],
) -> None:
    raw_decision = decision_metadata.get(CODE_MODE_DECISION_KEY)
    if not isinstance(raw_decision, Mapping):
        return
    nested_call_id = raw_decision.get("nested_tool_call_id")
    effective_args = raw_decision.get("effective_args")
    args_sha256 = raw_decision.get("args_sha256")
    tool_name = decision_metadata.get("nested_tool_name")
    if (
        not isinstance(nested_call_id, str)
        or not nested_call_id
        or not isinstance(effective_args, Mapping)
        or not isinstance(args_sha256, str)
        or not args_sha256
        or not isinstance(tool_name, str)
        or not tool_name
    ):
        return
    from services.agents.runtime.dispatch import (
        cleanup_staged_tool_content,
        digest_args,
        record_invocation,
    )
    from services.agents.runtime.tools.registry import resolve_runtime_tool_definition

    computed_digest, args_bytes = digest_args(dict(effective_args))
    if computed_digest != args_sha256 or not hasattr(deps, "workspace"):
        return
    definition = resolve_runtime_tool_definition(
        tool_name,
        _workspace_definitions(deps),
    )
    await record_invocation(
        deps=deps,
        tool_name=tool_name,
        tool_provider=definition.provider if definition is not None else "core",
        status=AuditStatus.DENIED,
        args=dict(effective_args),
        args_sha256=args_sha256,
        args_bytes=args_bytes,
        started=monotonic(),
        tool_call_id=nested_call_id,
        parent_tool_call_id=outer_tool_call_id,
        outcome="denied_approval",
        approval_ref=nested_call_id,
        error_code="ToolDenied",
    )
    await cleanup_staged_tool_content(
        deps=deps,
        tool_name=tool_name,
        args=dict(effective_args),
    )


async def _cleanup_unclaimable_approved_content(
    *,
    deps: RuntimeDeps,
    decision_metadata: Mapping[str, Any],
) -> None:
    raw_decision = decision_metadata.get(CODE_MODE_DECISION_KEY)
    tool_name = decision_metadata.get("nested_tool_name")
    if (
        not isinstance(raw_decision, Mapping)
        or raw_decision.get("decision") != "approved"
        or not isinstance(raw_decision.get("effective_args"), Mapping)
        or not isinstance(tool_name, str)
        or not hasattr(deps, "workspace")
    ):
        return
    from services.agents.runtime.dispatch import cleanup_staged_tool_content

    await cleanup_staged_tool_content(
        deps=deps,
        tool_name=tool_name,
        args=dict(raw_decision["effective_args"]),
    )


async def _record_failed_suspension_audit(
    *,
    deps: RuntimeDeps,
    outer_tool_call_id: str,
    approval_metadata: Mapping[str, Any],
) -> None:
    nested_call_id = approval_metadata.get("nested_tool_call_id")
    tool_name = approval_metadata.get("nested_tool_name")
    args = approval_metadata.get("nested_args")
    if (
        not hasattr(deps, "workspace")
        or not isinstance(nested_call_id, str)
        or not nested_call_id
        or not isinstance(tool_name, str)
        or not tool_name
        or not isinstance(args, Mapping)
    ):
        return
    from services.agents.runtime.dispatch import (
        cleanup_staged_tool_content,
        digest_args,
        record_invocation,
    )
    from services.agents.runtime.tools.registry import resolve_runtime_tool_definition

    args_sha256, args_bytes = digest_args(dict(args))
    definition = resolve_runtime_tool_definition(
        tool_name,
        _workspace_definitions(deps),
    )
    await record_invocation(
        deps=deps,
        tool_name=tool_name,
        tool_provider=definition.provider if definition is not None else "core",
        status=AuditStatus.FAILURE,
        args=dict(args),
        args_sha256=args_sha256,
        args_bytes=args_bytes,
        started=monotonic(),
        tool_call_id=nested_call_id,
        parent_tool_call_id=outer_tool_call_id,
        outcome="failed",
        approval_ref=nested_call_id,
        error_code="code_mode_snapshot_too_large",
    )
    await cleanup_staged_tool_content(deps=deps, tool_name=tool_name, args=dict(args))


def _recoverable_effects(metadata: object) -> tuple[list[CodeModeExecutedEffect], bool]:
    if not isinstance(metadata, Mapping):
        return [], True
    raw_state = metadata.get(CODE_MODE_STATE_METADATA_KEY)
    primary_present = CODE_MODE_STATE_METADATA_KEY in metadata
    primary_raw = raw_state.get("executed_effects") if isinstance(raw_state, Mapping) else raw_state
    if isinstance(raw_state, Mapping) and "executed_effects" not in raw_state:
        primary_present = False
    primary = _parse_effect_evidence(
        primary_raw,
        present=primary_present,
    )
    fallback_raw, fallback_present = _approval_effect_evidence(metadata)
    fallback = _parse_effect_evidence(fallback_raw, present=fallback_present)
    combined = _dedupe_effects([*primary[0], *fallback[0]])
    if not primary[1] or not fallback[1]:
        return combined, False
    if primary[2] and fallback[2] and set(primary[0]) != set(fallback[0]):
        return combined, False
    return combined, True


def _parse_effect_evidence(
    raw: object,
    *,
    present: bool,
) -> tuple[list[CodeModeExecutedEffect], bool, bool]:
    if not present:
        return [], True, False
    if not isinstance(raw, list) or len(raw) > CODE_MODE_STATE_EFFECT_LIMIT:
        return [], False, True
    effects: list[CodeModeExecutedEffect] = []
    valid = True
    for item in raw:
        if not isinstance(item, Mapping):
            valid = False
            continue
        values = (item.get("nested_call_id"), item.get("tool_name"), item.get("args_sha256"))
        if not all(isinstance(value, str) and value for value in values):
            valid = False
            continue
        effects.append(CodeModeExecutedEffect(*values))
    return effects, valid, True


def _approval_effect_evidence(metadata: Mapping[str, object]) -> tuple[object, bool]:
    approval_state = metadata.get("approval_state")
    deferred = (
        approval_state.get("deferred_tool_requests")
        if isinstance(approval_state, Mapping)
        else None
    )
    approval_metadata = deferred.get("metadata") if isinstance(deferred, Mapping) else None
    if isinstance(approval_metadata, Mapping):
        for item in approval_metadata.values():
            if isinstance(item, Mapping) and item.get("kind") == "code_mode":
                return item.get("executed_effects"), "executed_effects" in item
    return None, False


def _dedupe_effects(effects: list[CodeModeExecutedEffect]) -> list[CodeModeExecutedEffect]:
    return list(dict.fromkeys(effects))


def _clear_code_mode_state(run: Any) -> None:
    run.metadata_json = clear_code_mode_state_metadata(run)


def _redraft_result(reason: str) -> ToolReturn:
    return ToolReturn(
        return_value={
            "status": "failed",
            "error": (
                "The workflow could not be restored safely. The approval decision was kept; "
                "redraft the workflow before trying again."
            ),
            "degradation_reason": reason,
        }
    )


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


def _tool_summary(tool_name: str, workspace_definitions=()) -> str:
    from services.agents.runtime.tools.registry import resolve_runtime_tool_definition

    definition = resolve_runtime_tool_definition(tool_name, workspace_definitions)
    return (
        definition.label
        if definition is not None and definition.label
        else tool_name.replace("_", " ").title()
    )


def _workspace_definitions(deps):
    return getattr(deps, "workspace_tool_definitions", ())


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
