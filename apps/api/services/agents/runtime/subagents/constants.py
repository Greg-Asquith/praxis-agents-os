# apps/api/services/agents/runtime/subagents/constants.py

"""Sub-agent runtime constants."""

RUN_SUBAGENT_TOOL_NAME = "run_subagent"
SUBAGENT_METADATA_KEY = "subagent"
SUBAGENT_ROLE_MAX_LENGTH = 100
SUBAGENT_INSTRUCTIONS_MAX_LENGTH = 10000
SUBAGENT_NOT_ALLOWED_ERROR_MESSAGE = "Sub-agents are no longer enabled for this agent."
# Sub-agents read the parent's memory but never change it.
SUBAGENT_BLOCKED_TOOL_NAMES = frozenset({"save_memory", "update_memory", "forget_memory"})
