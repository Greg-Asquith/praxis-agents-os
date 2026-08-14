# apps/api/services/agents/runtime/code_mode/state.py

"""Build and validate durable Code Mode interpreter resume artifacts."""

from __future__ import annotations

import base64
import binascii
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from importlib.metadata import version
from typing import Any, Literal

from core.settings import settings
from models.agent_run import AgentRun

CODE_MODE_STATE_METADATA_KEY = "code_mode_state"
CODE_MODE_STATE_VERSION = 1
CODE_MODE_MONTY_VERSION = version("pydantic-monty")
CODE_MODE_STATE_TRACE_LIMIT = settings.AGENT_CODE_MODE_MAX_NESTED_CALLS
CODE_MODE_STATE_EFFECT_LIMIT = settings.AGENT_CODE_MODE_MAX_NESTED_CALLS
CODE_MODE_STATE_TAINT_SOURCE_LIMIT = 32

CodeModeDegradationReason = Literal[
    "missing_key",
    "schema_mismatch",
    "monty_version_mismatch",
    "snapshot_corrupt",
    "resume_crash",
    "snapshot_too_large",
]


@dataclass(frozen=True)
class CodeModeExecutedEffect:
    nested_call_id: str
    tool_name: str
    args_sha256: str


@dataclass(frozen=True)
class CodeModeConsumedBudget:
    elapsed_seconds: float
    nested_calls: int


@dataclass(frozen=True)
class CodeModeState:
    run_id: str
    conversation_id: str
    agent_id: str
    outer_tool_call_id: str
    nested_call_id: str
    code: str
    reason: str | None
    executed_call_count: int
    consumed_budget: CodeModeConsumedBudget
    executed_effects: tuple[CodeModeExecutedEffect, ...]
    nested_trace: tuple[dict[str, Any], ...]
    trace_truncated: bool
    tainted: bool
    taint_sources: tuple[dict[str, str], ...]
    taint_sources_overflow: int
    output: str
    output_truncated: bool
    snapshot: bytes


@dataclass
class CodeModeStateError(Exception):
    reason: CodeModeDegradationReason
    detail: str

    def __str__(self) -> str:
        return self.detail


@dataclass
class CodeModeResumeRequiresRecoveryError(Exception):
    reason: CodeModeDegradationReason
    executed_effects: tuple[CodeModeExecutedEffect, ...]

    def __str__(self) -> str:
        return "The workflow could not resume safely after completed actions."

    @property
    def completion_json(self) -> dict[str, Any]:
        return {
            "error_code": "code_mode_resume_requires_recovery",
            "degradation_reason": self.reason,
            "executed_effects": [effect.__dict__ for effect in self.executed_effects],
        }


def build_code_mode_state_metadata(
    *,
    run: AgentRun,
    outer_tool_call_id: str,
    nested_call_id: str,
    code: str,
    reason: str | None,
    snapshot: bytes,
    executed_call_count: int,
    elapsed_seconds: float,
    executed_effects: Sequence[Mapping[str, object]],
    nested_trace: Sequence[Mapping[str, object]],
    trace_truncated: bool = False,
    tainted: bool = False,
    taint_sources: Sequence[Mapping[str, object]] = (),
    taint_sources_overflow: int = 0,
    output: str = "",
    output_truncated: bool = False,
    snapshot_max_bytes: int,
    state_max_bytes: int,
) -> dict[str, Any]:
    """Return run metadata with one bounded, workspace-confidential resume artifact."""
    if len(snapshot) > snapshot_max_bytes:
        raise CodeModeStateError(
            "snapshot_too_large",
            f"Code Mode snapshot exceeds the {snapshot_max_bytes}-byte limit",
        )
    if executed_call_count < 0 or elapsed_seconds < 0:
        raise ValueError("Code Mode consumed budgets cannot be negative")
    if taint_sources_overflow < 0:
        raise ValueError("Code Mode taint overflow cannot be negative")

    effects = [_normalize_effect(item) for item in executed_effects]
    if len(effects) > CODE_MODE_STATE_EFFECT_LIMIT:
        raise ValueError("Code Mode executed-effects ledger exceeds its bound")
    trace = [dict(item) for item in nested_trace[:CODE_MODE_STATE_TRACE_LIMIT]]
    sources = [_normalize_taint_source(item) for item in taint_sources]
    if len(sources) > CODE_MODE_STATE_TAINT_SOURCE_LIMIT:
        raise ValueError("Code Mode taint-source list exceeds its bound")

    metadata = dict(run.metadata_json or {})
    state_metadata = {
        "version": CODE_MODE_STATE_VERSION,
        "monty_version": CODE_MODE_MONTY_VERSION,
        "run_id": str(run.id),
        "conversation_id": str(run.conversation_id),
        "agent_id": str(run.agent_id),
        "outer_tool_call_id": outer_tool_call_id,
        "nested_call_id": nested_call_id,
        "code": code,
        "reason": reason,
        "executed_call_count": executed_call_count,
        "consumed_budget": {
            "elapsed_seconds": elapsed_seconds,
            "nested_calls": executed_call_count,
        },
        "executed_effects": effects,
        "nested_trace": trace,
        "trace_truncated": trace_truncated or len(nested_trace) > len(trace),
        "tainted": tainted,
        "taint_sources": sources,
        "taint_sources_overflow": taint_sources_overflow,
        "output": output,
        "output_truncated": output_truncated,
        "snapshot_b64": base64.b64encode(snapshot).decode("ascii"),
    }
    for entry in trace:
        if _serialized_size(state_metadata) <= state_max_bytes:
            break
        if "presentation_result" in entry:
            entry.pop("presentation_result")
            entry["presentation_truncated"] = True
    if _serialized_size(state_metadata) > state_max_bytes:
        raise CodeModeStateError(
            "snapshot_too_large",
            f"Code Mode resume state exceeds the {state_max_bytes}-byte limit",
        )
    metadata[CODE_MODE_STATE_METADATA_KEY] = state_metadata
    return metadata


def load_code_mode_state(
    run: AgentRun,
    *,
    outer_tool_call_id: str | None = None,
    snapshot_max_bytes: int,
) -> CodeModeState:
    """Load a trusted database artifact and classify incompatible state precisely."""
    raw = (run.metadata_json or {}).get(CODE_MODE_STATE_METADATA_KEY)
    if not isinstance(raw, dict):
        raise CodeModeStateError("missing_key", "Agent run has no Code Mode resume state")
    if raw.get("monty_version") != CODE_MODE_MONTY_VERSION:
        raise CodeModeStateError(
            "monty_version_mismatch",
            "Code Mode snapshot was created by a different Monty version",
        )
    try:
        state = _parse_state(raw, snapshot_max_bytes=snapshot_max_bytes)
    except CodeModeStateError:
        raise
    except (KeyError, TypeError, ValueError) as exc:
        raise CodeModeStateError(
            "schema_mismatch", "Code Mode resume state has an unsupported shape"
        ) from exc
    if (
        state.run_id != str(run.id)
        or state.conversation_id != str(run.conversation_id)
        or state.agent_id != str(run.agent_id)
        or (outer_tool_call_id is not None and state.outer_tool_call_id != outer_tool_call_id)
    ):
        raise CodeModeStateError(
            "schema_mismatch", "Code Mode resume state does not belong to this run"
        )
    return state


def clear_code_mode_state_metadata(run: AgentRun) -> dict[str, Any] | None:
    """Return run metadata without the resume artifact; repeated clearing is safe."""
    metadata = dict(run.metadata_json or {})
    metadata.pop(CODE_MODE_STATE_METADATA_KEY, None)
    return metadata or None


def classify_snapshot_load_failure(exc: BaseException) -> CodeModeStateError:
    """Separate invalid snapshot bytes from failures after a valid restore begins."""
    from pydantic_monty import MontyCrashedError, MontyRuntimeError

    failed_during_load = isinstance(exc, MontyRuntimeError) and (
        "failed to load session" in str(exc).lower()
    )
    reason: CodeModeDegradationReason = (
        "resume_crash"
        if isinstance(exc, (MontyCrashedError, TimeoutError))
        or (isinstance(exc, MontyRuntimeError) and not failed_during_load)
        else "snapshot_corrupt"
    )
    return CodeModeStateError(reason, f"Code Mode snapshot restore failed: {type(exc).__name__}")


def append_executed_effect(
    effects: Sequence[CodeModeExecutedEffect],
    *,
    nested_call_id: str,
    tool_name: str,
    args_sha256: str,
) -> tuple[CodeModeExecutedEffect, ...]:
    """Append one completed effect while preserving a strict durable bound."""
    if len(effects) >= CODE_MODE_STATE_EFFECT_LIMIT:
        raise ValueError("Code Mode executed-effects ledger exceeds its bound")
    return (*effects, CodeModeExecutedEffect(nested_call_id, tool_name, args_sha256))


def _parse_state(raw: Mapping[str, Any], *, snapshot_max_bytes: int) -> CodeModeState:
    if raw["version"] != CODE_MODE_STATE_VERSION:
        raise ValueError("unsupported version")
    snapshot_b64 = raw["snapshot_b64"]
    if not isinstance(snapshot_b64, str):
        raise TypeError("snapshot_b64 must be a string")
    try:
        snapshot = base64.b64decode(snapshot_b64, validate=True)
    except (ValueError, binascii.Error) as exc:
        raise CodeModeStateError(
            "snapshot_corrupt", "Code Mode snapshot is not valid base64"
        ) from exc
    if len(snapshot) > snapshot_max_bytes:
        raise CodeModeStateError(
            "snapshot_corrupt", "Code Mode snapshot exceeds its configured bound"
        )

    budget = raw["consumed_budget"]
    effects = tuple(
        CodeModeExecutedEffect(**_normalize_effect(item)) for item in raw["executed_effects"]
    )
    trace = tuple(_normalize_trace_entry(item) for item in raw["nested_trace"])
    sources = tuple(_normalize_taint_source(item) for item in raw["taint_sources"])
    if (
        len(effects) > CODE_MODE_STATE_EFFECT_LIMIT
        or len(trace) > CODE_MODE_STATE_TRACE_LIMIT
        or len(sources) > CODE_MODE_STATE_TAINT_SOURCE_LIMIT
    ):
        raise ValueError("bounded collection exceeded")
    state = CodeModeState(
        run_id=_required_str(raw, "run_id"),
        conversation_id=_required_str(raw, "conversation_id"),
        agent_id=_required_str(raw, "agent_id"),
        outer_tool_call_id=_required_str(raw, "outer_tool_call_id"),
        nested_call_id=_required_str(raw, "nested_call_id"),
        code=_required_str(raw, "code"),
        reason=raw.get("reason") if isinstance(raw.get("reason"), str) else None,
        executed_call_count=_nonnegative_int(raw, "executed_call_count"),
        consumed_budget=CodeModeConsumedBudget(
            elapsed_seconds=_nonnegative_number(budget, "elapsed_seconds"),
            nested_calls=_nonnegative_int(budget, "nested_calls"),
        ),
        executed_effects=effects,
        nested_trace=trace,
        trace_truncated=_required_bool(raw, "trace_truncated"),
        tainted=_required_bool(raw, "tainted"),
        taint_sources=sources,
        taint_sources_overflow=_nonnegative_int(raw, "taint_sources_overflow"),
        output=_required_str(raw, "output", allow_empty=True),
        output_truncated=_required_bool(raw, "output_truncated"),
        snapshot=snapshot,
    )
    if state.consumed_budget.nested_calls != state.executed_call_count:
        raise ValueError("nested-call budget mismatch")
    return state


def _normalize_effect(item: Mapping[str, object]) -> dict[str, str]:
    return {
        "nested_call_id": _required_str(item, "nested_call_id"),
        "tool_name": _required_str(item, "tool_name"),
        "args_sha256": _required_str(item, "args_sha256"),
    }


def _normalize_taint_source(item: Mapping[str, object]) -> dict[str, str]:
    return {
        "source_kind": _required_str(item, "source_kind"),
        "source_ref": _required_str(item, "source_ref"),
    }


def _normalize_trace_entry(item: Mapping[str, object]) -> dict[str, Any]:
    normalized = dict(item)
    for key in ("tool_call_id", "parent_tool_call_id", "tool_name", "args_sha256", "summary"):
        _required_str(item, key)
    status = _required_str(item, "status")
    if status not in {"pending", "succeeded", "failed", "denied"}:
        raise ValueError("status is not a supported trace status")
    order = _nonnegative_int(item, "order")
    if order < 1:
        raise ValueError("order must be a positive integer")
    excerpt = item.get("excerpt")
    if excerpt is not None and not isinstance(excerpt, str):
        raise TypeError("excerpt must be a string or null")
    presentation_truncated = item.get("presentation_truncated", False)
    if not isinstance(presentation_truncated, bool):
        raise TypeError("presentation_truncated must be a boolean")
    if presentation_truncated or "presentation_truncated" in item:
        normalized["presentation_truncated"] = presentation_truncated
    return normalized


def _serialized_size(value: object) -> int:
    return len(
        json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(",", ":")).encode()
    )


def _required_str(item: Mapping[str, object], key: str, *, allow_empty: bool = False) -> str:
    value = item[key]
    if not isinstance(value, str) or (not allow_empty and not value):
        raise ValueError(f"{key} must be a non-empty string")
    return value


def _required_bool(item: Mapping[str, object], key: str) -> bool:
    value = item[key]
    if not isinstance(value, bool):
        raise TypeError(f"{key} must be a boolean")
    return value


def _nonnegative_int(item: Mapping[str, object], key: str) -> int:
    value = item[key]
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ValueError(f"{key} must be a non-negative integer")
    return value


def _nonnegative_number(item: Mapping[str, object], key: str) -> float:
    value = item[key]
    if not isinstance(value, (int, float)) or isinstance(value, bool) or value < 0:
        raise ValueError(f"{key} must be a non-negative number")
    return float(value)
