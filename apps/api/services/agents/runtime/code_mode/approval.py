# apps/api/services/agents/runtime/code_mode/approval.py

"""Trusted metadata contract for one suspended nested Code Mode approval."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from pydantic_ai.messages import ToolCallPart

CODE_MODE_APPROVAL_KIND_KEY = "kind"
CODE_MODE_APPROVAL_KIND = "code_mode"
CODE_MODE_APPROVAL_OUTER_CALL_ID_KEY = "outer_tool_call_id"
CODE_MODE_APPROVAL_NESTED_CALL_ID_KEY = "nested_tool_call_id"
CODE_MODE_APPROVAL_TOOL_NAME_KEY = "nested_tool_name"
CODE_MODE_APPROVAL_ARGS_KEY = "nested_args"
CODE_MODE_APPROVAL_REASON_KEY = "reason"
CODE_MODE_APPROVAL_DERIVED_KEY = "derived_from_untrusted"
CODE_MODE_APPROVAL_TAINT_SOURCES_KEY = "taint_sources"
CODE_MODE_DECISION_KEY = "code_mode_decision"


def build_code_mode_approval_metadata(
    *,
    outer_tool_call_id: str,
    nested_call: ToolCallPart,
    reason: str | None,
    derived_from_untrusted: bool = False,
    taint_sources: list[dict[str, str]] | None = None,
) -> dict[str, Any]:
    """Describe the nested action without exposing interpreter state to clients."""
    return {
        CODE_MODE_APPROVAL_KIND_KEY: CODE_MODE_APPROVAL_KIND,
        CODE_MODE_APPROVAL_OUTER_CALL_ID_KEY: outer_tool_call_id,
        CODE_MODE_APPROVAL_NESTED_CALL_ID_KEY: nested_call.tool_call_id,
        CODE_MODE_APPROVAL_TOOL_NAME_KEY: nested_call.tool_name,
        CODE_MODE_APPROVAL_ARGS_KEY: nested_call.args_as_dict(),
        CODE_MODE_APPROVAL_REASON_KEY: reason,
        CODE_MODE_APPROVAL_DERIVED_KEY: derived_from_untrusted,
        CODE_MODE_APPROVAL_TAINT_SOURCES_KEY: list(taint_sources or ()),
    }


def code_mode_nested_call(metadata: object) -> ToolCallPart | None:
    """Return the pending nested call only for a complete trusted discriminator."""
    if not isinstance(metadata, Mapping):
        return None
    if metadata.get(CODE_MODE_APPROVAL_KIND_KEY) != CODE_MODE_APPROVAL_KIND:
        return None
    call_id = metadata.get(CODE_MODE_APPROVAL_NESTED_CALL_ID_KEY)
    tool_name = metadata.get(CODE_MODE_APPROVAL_TOOL_NAME_KEY)
    args = metadata.get(CODE_MODE_APPROVAL_ARGS_KEY)
    if (
        not isinstance(call_id, str)
        or not call_id
        or not isinstance(tool_name, str)
        or not tool_name
    ):
        return None
    if not isinstance(args, Mapping):
        return None
    return ToolCallPart(tool_name=tool_name, args=dict(args), tool_call_id=call_id)


def build_code_mode_decision_metadata(
    *,
    approval_metadata: Mapping[str, Any],
    decision: str,
    effective_args: Mapping[str, Any],
    args_sha256: str,
    message: str | None,
) -> dict[str, Any]:
    """Carry one nested decision through Pydantic AI's tool-context metadata channel."""
    return {
        **dict(approval_metadata),
        CODE_MODE_DECISION_KEY: {
            "nested_tool_call_id": approval_metadata[CODE_MODE_APPROVAL_NESTED_CALL_ID_KEY],
            "decision": decision,
            "effective_args": dict(effective_args),
            "args_sha256": args_sha256,
            "message": message,
        },
    }
