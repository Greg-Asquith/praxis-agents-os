# apps/api/services/agents/runtime/execute/errors.py

"""Map internal execute-run exceptions to the public failure contract."""

from dataclasses import dataclass
from typing import Any

from pydantic_ai import UsageLimitExceeded
from pydantic_ai.exceptions import ModelHTTPError

from core.exceptions.general import ConflictError
from services.agents.models.domain import ModelConfigurationError
from services.agents.runtime.execution_control import ExecutionInterruptedError, InterruptionReason
from services.agents.runtime.usage_limits import BudgetLimitExceeded

DEFAULT_RUN_ERROR_CODE = "agent_run_failed"
DEFAULT_RUN_ERROR_MESSAGE = "The agent run failed unexpectedly."


@dataclass(frozen=True)
class PublicRunError:
    """Client-safe fields persisted and emitted for a failed agent run."""

    code: str
    message: str
    completion_json: dict[str, Any] | None = None


_BUDGET_KINDS = {
    "request_limit": "requests",
    "input_tokens_limit": "input_tokens",
    "output_tokens_limit": "output_tokens",
    "total_tokens_limit": "total_tokens",
    "tool_calls_limit": "tool_calls",
    "per_request_input_tokens_limit": "per_request_input_tokens",
    "cost_limit": "cost",
}


def public_run_error(exc: Exception) -> PublicRunError:
    """Return the explicit public mapping for an execute-run exception."""
    from services.agent_runs.continuation_state import AgentRunResumeRequiresRecoveryError
    from services.agents.runtime.code_mode.state import CodeModeResumeRequiresRecoveryError

    if isinstance(exc, AgentRunResumeRequiresRecoveryError):
        return PublicRunError(
            code="agent_run_resume_requires_recovery",
            message=str(exc),
            completion_json=exc.completion_json,
        )

    if isinstance(exc, ExecutionInterruptedError):
        messages = {
            InterruptionReason.DURATION_EXPIRED: "The agent run reached its time limit.",
            InterruptionReason.LEASE_LOST: "The agent run stopped because execution ownership could not be confirmed.",
            InterruptionReason.PARENT_TERMINATED: "The specialist stopped because its parent run ended.",
            InterruptionReason.PROCESS_SHUTDOWN: "The agent run stopped during service shutdown.",
            InterruptionReason.REQUESTED_CANCELLATION: "The agent run was stopped.",
        }
        return PublicRunError(code=exc.reason.value, message=messages[exc.reason])
    if isinstance(exc, ModelConfigurationError):
        return PublicRunError(
            code=str(getattr(exc, "error_code", "model_configuration_error")),
            message=str(exc),
        )
    if isinstance(exc, ModelHTTPError) and exc.status_code == 429:
        return PublicRunError(
            code="model_rate_limited",
            message=(
                "The model provider is limiting requests. Try again later. "
                "If this continues, ask your administrator to check model access and quota."
            ),
        )
    if isinstance(exc, ConflictError):
        return PublicRunError(
            code="agent_run_conflict",
            message=str(exc),
        )
    if isinstance(exc, UsageLimitExceeded):
        tripped_budget = _tripped_budget(exc)
        completion = {
            "error_code": "usage_limit_exceeded",
            **({"tripped_budget": tripped_budget} if tripped_budget is not None else {}),
        }
        if isinstance(exc, BudgetLimitExceeded):
            for name in ("observed_total_tokens", "requests"):
                value = getattr(exc, name)
                if type(value) is int:
                    completion[name] = min(2**53 - 1, max(0, value))
        return PublicRunError(
            code="usage_limit_exceeded",
            message=_usage_limit_message(completion),
            completion_json=completion,
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
    if isinstance(exc, BudgetLimitExceeded):
        kind = _BUDGET_KINDS.get(exc.kind)
        if kind is None:
            return None
        return {
            "kind": kind,
            "limit": exc.limit if isinstance(exc.limit, int) else str(exc.limit),
            "scope": "inherited" if exc.inherited else "local",
        }
    return None


def _usage_limit_message(completion: dict[str, Any]) -> str:
    tripped_budget = completion.get("tripped_budget")
    kind = tripped_budget.get("kind") if tripped_budget is not None else None
    if (
        kind == "total_tokens"
        and "observed_total_tokens" in completion
        and "requests" in completion
    ):
        requests = completion["requests"]
        noun = "request" if requests == 1 else "requests"
        return (
            f"This run stopped after counting {completion['observed_total_tokens']:,} tokens "
            f"across {requests:,} {noun}; the limit for this run is {tripped_budget['limit']:,}. "
            "Start a new conversation or shorten the context to continue."
        )
    messages = {
        "requests": "The agent run stopped after reaching its request budget.",
        "input_tokens": "The agent run stopped after reaching its input token budget.",
        "output_tokens": "The agent run stopped after reaching its output token budget.",
        "total_tokens": "The agent run stopped after reaching its total token budget.",
        "tool_calls": "The agent run stopped after reaching its tool-call budget.",
    }
    return messages.get(str(kind), "The agent run exceeded its configured usage limit.")
