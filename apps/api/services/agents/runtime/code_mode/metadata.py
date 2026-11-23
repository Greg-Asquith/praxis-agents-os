# apps/api/services/agents/runtime/code_mode/metadata.py

"""Shared tool name and metadata keys for nested Code Mode dispatch."""

from collections.abc import Mapping

from core.settings import settings

RUN_CODE_TOOL_NAME = "run_code"
CODE_MODE_PARENT_TOOL_CALL_METADATA_KEY = "praxis_code_mode_parent_tool_call_id"
CODE_MODE_HANDLER_STARTED_METADATA_KEY = "praxis_code_mode_handler_started"
CODE_MODE_DERIVED_FROM_UNTRUSTED_METADATA_KEY = "praxis_code_mode_derived_from_untrusted"
CODE_MODE_TAINT_SOURCES_METADATA_KEY = "praxis_code_mode_taint_sources"
CODE_MODE_PENDING_AUDIT_RECORDED_ATTR = "_praxis_code_mode_pending_audit_recorded"


def called_from_script(ctx: object) -> bool:
    """True when a run_code script made this call, so the model never reads its result."""
    metadata = getattr(ctx, "tool_call_metadata", None)
    return isinstance(metadata, Mapping) and bool(
        metadata.get(CODE_MODE_PARENT_TOOL_CALL_METADATA_KEY)
    )


def script_text_max_chars() -> int:
    """Text one call returns to a script; JSON escaping can grow a character to 4 bytes."""
    return settings.AGENT_CODE_MODE_VALUE_MAX_BYTES // 4
