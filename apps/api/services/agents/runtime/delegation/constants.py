# apps/api/services/agents/runtime/delegation/constants.py

"""Delegation runtime constants."""

DELEGATE_TASK_MAX_LENGTH = 12000
DELEGATE_TASK_PREVIEW_MAX_LENGTH = 500
DELEGATE_OUTPUT_PREVIEW_MAX_LENGTH = 4000
DELEGATE_NOT_ALLOWED_ERROR_CODE = "delegate_agent_not_allowed"
DELEGATE_NOT_ALLOWED_ERROR_MESSAGE = (
    "Delegate agent is no longer allowed for this parent agent."
)
