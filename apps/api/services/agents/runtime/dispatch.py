# apps/api/services/agents/runtime/dispatch.py

"""Runtime tool dispatch choke point.

Hook probe findings, recorded 2026-07-03 against the installed ``pydantic-ai``
package:
- ``Hooks.on`` exposes ``before_tool_execute``, ``after_tool_execute``,
  ``tool_execute``, ``tool_execute_error``, and ``before_tool_validate``.
- Tool execution hooks receive ``RunContext.deps`` and fire for tools mounted
  through the agent ``tools=[...]`` argument.
- Raising ``ModelRetry`` from a tool-execution hook prevents the tool body from
  running and returns a model-visible retry message.
- Approval-required tools do not fire execution hooks when the approval request
  is created or when a denial is replayed. Approved replay does fire hooks with
  ``ctx.tool_call_approved`` true, so denied approvals are audited from the
  ``execute_run`` resume path.

Mount strategy: an always-loaded ``Hooks`` capability uses ``wrap_tool_execute``
to keep timing, envelope checks, output validation, mutation warnings, and audit
emission in one invocation-local scope. Future instrumentation should wrap this
module rather than adding another interception layer.
"""

import hashlib
import json
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass
from time import monotonic
from typing import Any

from pydantic import ValidationError
from pydantic_ai import ApprovalRequired, DeferredToolResults, ModelRetry, ToolDenied
from pydantic_ai.messages import ModelMessage, NativeToolCallPart, NativeToolReturnPart

from services.agents.runtime.context import RuntimeDeps
from services.agents.runtime.delegation.tool_names import DELEGATION_TOOL_NAMES
from services.agents.runtime.tools.contract import (
    TOOL_EFFECT_WRITE,
    RuntimeToolDefinition,
)
from services.agents.runtime.tools.registry import RUNTIME_TOOL_CATALOG
from services.audit_events.enums import AuditStatus
from services.audit_events.tool_events import (
    ToolAuditOutcome,
    record_tool_invocation_audit_event,
)

Handler = Callable[[Mapping[str, Any]], Awaitable[Any]]

MUTATION_OUTPUT_WARNING = (
    "the external action may have completed - verify before retrying; "
    "tool output did not match the declared schema"
)
READ_OUTPUT_WARNING = "Tool output did not match the declared schema."
ENVELOPE_DENIAL_MESSAGE = "Tool execution denied by this run's side-effect policy."


@dataclass(frozen=True)
class OutputContractError(Exception):
    """Internal signal for a model-visible output-contract retry."""

    retry_message: str
    outcome: ToolAuditOutcome


def digest_args(args: Mapping[str, Any] | None) -> tuple[str, int]:
    """Return a stable SHA-256 digest and byte count for tool arguments."""
    raw = json.dumps(
        args or {},
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode()
    return hashlib.sha256(raw).hexdigest(), len(raw)


def _tool_call_args_for_digest(args: Any) -> Mapping[str, Any]:
    if isinstance(args, Mapping):
        return args
    if isinstance(args, str):
        try:
            parsed = json.loads(args)
        except json.JSONDecodeError:
            return {"args": args}
        if isinstance(parsed, Mapping):
            return parsed
        return {"args": parsed}
    return {"args": args}


def check_envelope(
    definition: RuntimeToolDefinition | None,
    deps: RuntimeDeps,
) -> str | None:
    """Return a model-visible denial message when the run envelope blocks a tool."""
    if definition is None:
        return None
    if definition.effect == TOOL_EFFECT_WRITE and deps.envelope.side_effect_policy == "deny":
        return ENVELOPE_DENIAL_MESSAGE
    return None


def validate_output(
    definition: RuntimeToolDefinition | None,
    result: Any,
) -> None:
    """Validate a declared output model or raise a model-visible retry signal."""
    if definition is None or definition.output_model is None:
        return
    try:
        definition.output_model.model_validate(result)
    except ValidationError as exc:
        if definition.effect == TOOL_EFFECT_WRITE:
            raise OutputContractError(
                retry_message=f"{MUTATION_OUTPUT_WARNING}: {exc}",
                outcome="unverified_mutation",
            ) from exc
        raise OutputContractError(
            retry_message=f"{READ_OUTPUT_WARNING} {exc}",
            outcome="failed",
        ) from exc


async def dispatch_tool_execution(
    ctx,
    *,
    call,
    tool_def,
    args: Mapping[str, Any],
    handler: Handler,
) -> Any:
    """Execute one Pydantic AI tool through the Praxis dispatch policy."""
    tool_name = call.tool_name
    definition = RUNTIME_TOOL_CATALOG.get(tool_name)
    tool_provider = _tool_provider(tool_name, definition)
    args_sha256, args_bytes = digest_args(args)
    started = monotonic()
    tool_call_id = call.tool_call_id
    approval_ref = call.tool_call_id if getattr(ctx, "tool_call_approved", False) else None

    denial_message = check_envelope(definition, ctx.deps)
    if denial_message is not None:
        await record_invocation(
            deps=ctx.deps,
            tool_name=tool_name,
            tool_provider=tool_provider,
            status=AuditStatus.DENIED,
            args=args,
            args_sha256=args_sha256,
            args_bytes=args_bytes,
            started=started,
            tool_call_id=tool_call_id,
            outcome="denied_envelope",
            approval_ref=approval_ref,
        )
        raise ModelRetry(denial_message)

    try:
        result = await handler(args)
    except ApprovalRequired:
        await record_invocation(
            deps=ctx.deps,
            tool_name=tool_name,
            tool_provider=tool_provider,
            status=AuditStatus.PENDING,
            args=args,
            args_sha256=args_sha256,
            args_bytes=args_bytes,
            started=started,
            tool_call_id=tool_call_id,
            outcome="approval_requested",
            approval_ref=call.tool_call_id,
        )
        raise
    except Exception as exc:
        await record_invocation(
            deps=ctx.deps,
            tool_name=tool_name,
            tool_provider=tool_provider,
            status=AuditStatus.FAILURE,
            args=args,
            args_sha256=args_sha256,
            args_bytes=args_bytes,
            started=started,
            tool_call_id=tool_call_id,
            outcome="failed",
            approval_ref=approval_ref,
            error_code=exc.__class__.__name__,
        )
        raise

    try:
        validate_output(definition, result)
    except OutputContractError as exc:
        await record_invocation(
            deps=ctx.deps,
            tool_name=tool_name,
            tool_provider=tool_provider,
            status=AuditStatus.FAILURE,
            args=args,
            args_sha256=args_sha256,
            args_bytes=args_bytes,
            started=started,
            tool_call_id=tool_call_id,
            outcome=exc.outcome,
            approval_ref=approval_ref,
            error_code="OutputContractValidationError",
        )
        raise ModelRetry(exc.retry_message) from exc

    await record_invocation(
        deps=ctx.deps,
        tool_name=tool_name,
        tool_provider=tool_provider,
        status=AuditStatus.SUCCESS,
        args=args,
        args_sha256=args_sha256,
        args_bytes=args_bytes,
        started=started,
        tool_call_id=tool_call_id,
        outcome="completed",
        approval_ref=approval_ref,
    )
    return result


async def record_denied_approval_audit_events(
    *,
    deps: RuntimeDeps,
    message_history: Sequence[ModelMessage],
    deferred_tool_results: DeferredToolResults,
) -> None:
    """Audit approval denials because Pydantic AI skips execution hooks for them."""
    tool_calls = _tool_calls_by_id(message_history)
    for tool_call_id, approval_result in deferred_tool_results.approvals.items():
        if not isinstance(approval_result, ToolDenied):
            continue
        call = tool_calls.get(tool_call_id)
        tool_name = getattr(call, "tool_name", "unknown_tool")
        args = _tool_call_args_for_digest(getattr(call, "args", None))
        definition = RUNTIME_TOOL_CATALOG.get(tool_name)
        args_sha256, args_bytes = digest_args(args)
        await record_invocation(
            deps=deps,
            tool_name=tool_name,
            tool_provider=_tool_provider(tool_name, definition),
            status=AuditStatus.DENIED,
            args=args,
            args_sha256=args_sha256,
            args_bytes=args_bytes,
            started=monotonic(),
            tool_call_id=tool_call_id,
            outcome="denied_approval",
            approval_ref=tool_call_id,
            error_code="ToolDenied",
        )


async def record_native_tool_invocation_audit_event(
    *,
    deps: RuntimeDeps,
    call_part: NativeToolCallPart | None,
    return_part: NativeToolReturnPart,
) -> None:
    """Audit one provider-native tool invocation observed in the event stream."""
    args = _tool_call_args_for_digest(getattr(call_part, "args", None))
    args_sha256, args_bytes = digest_args(args)
    status, outcome = _native_audit_status_and_outcome(return_part)
    await record_tool_invocation_audit_event(
        workspace_id=deps.workspace.id,
        agent=deps.agent,
        run=deps.run,
        tool_name=return_part.tool_name,
        tool_provider="native",
        tool_call_id=return_part.tool_call_id,
        status=status,
        args=dict(args),
        args_sha256=args_sha256,
        args_bytes=args_bytes,
        latency_ms=None,
        outcome=outcome,
        approval_ref=None,
        error_code=_native_error_code(return_part),
    )


async def record_invocation(
    *,
    deps: RuntimeDeps,
    tool_name: str,
    tool_provider: str,
    status: AuditStatus,
    args: Mapping[str, Any],
    args_sha256: str,
    args_bytes: int,
    started: float,
    tool_call_id: str,
    outcome: ToolAuditOutcome,
    approval_ref: str | None = None,
    error_code: str | None = None,
) -> None:
    """Assemble and persist one invocation audit event."""
    await record_tool_invocation_audit_event(
        workspace_id=deps.workspace.id,
        agent=deps.agent,
        run=deps.run,
        tool_name=tool_name,
        tool_provider=tool_provider,
        tool_call_id=tool_call_id,
        status=status,
        args=dict(args),
        args_sha256=args_sha256,
        args_bytes=args_bytes,
        latency_ms=max(1, int((monotonic() - started) * 1000)),
        outcome=outcome,
        approval_ref=approval_ref,
        error_code=error_code,
    )


def _tool_provider(
    tool_name: str,
    definition: RuntimeToolDefinition | None,
) -> str:
    if definition is not None:
        return definition.provider
    if tool_name in DELEGATION_TOOL_NAMES:
        return "delegation"
    return "runtime"


def _native_audit_status_and_outcome(
    return_part: NativeToolReturnPart,
) -> tuple[AuditStatus, ToolAuditOutcome]:
    if return_part.outcome == "success":
        return AuditStatus.SUCCESS, "completed"
    if return_part.outcome == "denied":
        return AuditStatus.DENIED, "denied_approval"
    return AuditStatus.FAILURE, "failed"


def _native_error_code(return_part: NativeToolReturnPart) -> str | None:
    if return_part.outcome == "success":
        return None
    provider_details = return_part.provider_details or {}
    error_code = provider_details.get("error_code")
    if error_code is not None:
        return str(error_code)
    content = return_part.content
    if isinstance(content, Mapping):
        content_error_code = content.get("error_code") or content.get("code")
        if content_error_code is not None:
            return str(content_error_code)
    return f"NativeTool{str(return_part.outcome).capitalize()}"


def _tool_calls_by_id(messages: Sequence[ModelMessage]) -> dict[str, Any]:
    calls: dict[str, Any] = {}
    for message in messages:
        for part in getattr(message, "parts", []):
            if getattr(part, "part_kind", None) == "tool-call":
                calls[part.tool_call_id] = part
    return calls
