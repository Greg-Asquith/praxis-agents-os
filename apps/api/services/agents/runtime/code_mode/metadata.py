# apps/api/services/agents/runtime/code_mode/metadata.py

"""Shared metadata keys for nested Code Mode dispatch."""

CODE_MODE_PARENT_TOOL_CALL_METADATA_KEY = "praxis_code_mode_parent_tool_call_id"
CODE_MODE_HANDLER_STARTED_METADATA_KEY = "praxis_code_mode_handler_started"
CODE_MODE_DERIVED_FROM_UNTRUSTED_METADATA_KEY = "praxis_code_mode_derived_from_untrusted"
CODE_MODE_TAINT_SOURCES_METADATA_KEY = "praxis_code_mode_taint_sources"
CODE_MODE_PENDING_AUDIT_RECORDED_ATTR = "_praxis_code_mode_pending_audit_recorded"
