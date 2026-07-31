# apps/api/services/agents/runtime/execute/errors.py

"""Map internal execute-run exceptions to the public failure contract."""

from dataclasses import dataclass

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


def public_run_error(exc: Exception) -> PublicRunError:
    """Return the explicit public mapping for an execute-run exception."""
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
        return PublicRunError(
            code="usage_limit_exceeded",
            message="The agent run exceeded its configured usage limit.",
        )
    return PublicRunError(
        code=DEFAULT_RUN_ERROR_CODE,
        message=DEFAULT_RUN_ERROR_MESSAGE,
    )
