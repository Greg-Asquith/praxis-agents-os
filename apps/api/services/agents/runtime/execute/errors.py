# apps/api/services/agents/runtime/execute/errors.py

"""Map internal execute-run exceptions to the public failure contract."""

import re
from dataclasses import dataclass
from typing import Any

from pydantic_ai import UsageLimitExceeded

from core.exceptions.general import ConflictError
from services.agents.models.domain import ModelConfigurationError

DEFAULT_RUN_ERROR_CODE = "agent_run_failed"
DEFAULT_RUN_ERROR_MESSAGE = "The agent run failed unexpectedly."


@dataclass(frozen=True)
class PublicRunError:
    """Client-safe fields persisted and emitted for a failed agent run."""

    code: str
    message: str
    completion_json: dict[str, Any] | None = None


_USAGE_LIMIT_PATTERN = re.compile(
    r"(?:exceed|exceeded) the "
    r"(?P<kind>request_limit|input_tokens_limit|output_tokens_limit|total_tokens_limit|tool_calls_limit) "
    r"of (?P<limit>\d+)",
    re.IGNORECASE,
)
_BUDGET_KINDS = {
    "request_limit": "requests",
    "input_tokens_limit": "input_tokens",
    "output_tokens_limit": "output_tokens",
    "total_tokens_limit": "total_tokens",
    "tool_calls_limit": "tool_calls",
}


def public_run_error(exc: Exception) -> PublicRunError:
    """Return the explicit public mapping for an execute-run exception."""
    from services.agents.runtime.code_mode.state import CodeModeResumeRequiresRecoveryError

    if isinstance(exc, ModelConfigurationError):
        return PublicRunError(
            code=str(getattr(exc, "error_code", "model_configuration_error")),
            message=str(exc),
        )
    if isinstance(exc, ConflictError):
        return PublicRunError(
            code="agent_run_conflict",
            message=str(exc),
        )
    if isinstance(exc, UsageLimitExceeded):
        tripped_budget = _tripped_budget(exc)
        return PublicRunError(
            code="usage_limit_exceeded",
            message=_usage_limit_message(tripped_budget),
            completion_json={
                "error_code": "usage_limit_exceeded",
                **({"tripped_budget": tripped_budget} if tripped_budget is not None else {}),
            },
        )
    if isinstance(exc, CodeModeResumeRequiresRecoveryError):
        return PublicRunError(
            code="code_mode_resume_requires_recovery",
            message=(
                "This workflow stopped because its saved state could not be restored after "
                "one or more actions completed. Review the completed actions before continuing."
            ),
            completion_json=exc.completion_json,
        )
    return PublicRunError(
        code=DEFAULT_RUN_ERROR_CODE,
        message=DEFAULT_RUN_ERROR_MESSAGE,
    )


def _tripped_budget(exc: UsageLimitExceeded) -> dict[str, str | int] | None:
    """Extract only allowlisted framework limit metadata from the exception."""
    match = _USAGE_LIMIT_PATTERN.search(str(exc))
    if match is None:
        return None
    return {
        "kind": _BUDGET_KINDS[match.group("kind").lower()],
        "limit": int(match.group("limit")),
    }


def _usage_limit_message(tripped_budget: dict[str, str | int] | None) -> str:
    kind = tripped_budget.get("kind") if tripped_budget is not None else None
    messages = {
        "requests": "The agent run stopped after reaching its request budget.",
        "input_tokens": "The agent run stopped after reaching its input token budget.",
        "output_tokens": "The agent run stopped after reaching its output token budget.",
        "total_tokens": "The agent run stopped after reaching its total token budget.",
        "tool_calls": "The agent run stopped after reaching its tool-call budget.",
    }
    return messages.get(str(kind), "The agent run exceeded its configured usage limit.")
