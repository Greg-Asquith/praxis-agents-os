# apps/api/services/agents/runtime/completion_contract.py

"""Validated completion-report contracts for unattended schedule runs."""

import json
from collections.abc import Mapping
from typing import Annotated, Any

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    ValidationError,
    model_validator,
)

COMPLETION_CONTRACT_KEY = "completion_contract"
REPORT_COMPLETION_TOOL_NAME = "report_completion"
MAX_COMPLETION_CRITERIA = 20
MAX_COMPLETION_CRITERION_LENGTH = 500
MAX_COMPLETION_JSON_BYTES = 72 * 1024
MAX_SCHEDULE_BUDGET = (2**53) - 1

CompletionCriterion = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True, min_length=1, max_length=MAX_COMPLETION_CRITERION_LENGTH
    ),
]


class ScheduleCompletionContract(BaseModel):
    """Operator-declared completion criteria and tighter per-run budgets."""

    required: bool
    criteria: list[CompletionCriterion] = Field(
        default_factory=list,
        max_length=MAX_COMPLETION_CRITERIA,
    )
    max_requests: int | None = Field(default=None, strict=True, ge=1, le=MAX_SCHEDULE_BUDGET)
    max_total_tokens: int | None = Field(default=None, strict=True, ge=1, le=MAX_SCHEDULE_BUDGET)

    model_config = ConfigDict(extra="allow")

    @model_validator(mode="after")
    def require_criteria_for_report(self) -> "ScheduleCompletionContract":
        if self.required and not self.criteria:
            raise ValueError("criteria must contain at least one item when a report is required")
        return self


def completion_contract_from_execution_params(
    execution_params: object,
) -> ScheduleCompletionContract | None:
    """Read a completion contract from extensible schedule execution parameters."""
    if not isinstance(execution_params, Mapping):
        return None
    raw_contract = execution_params.get(COMPLETION_CONTRACT_KEY)
    if raw_contract is None:
        return None
    try:
        return ScheduleCompletionContract.model_validate(raw_contract)
    except ValidationError:
        return None


def completion_contract_from_run_metadata(
    metadata: object,
) -> ScheduleCompletionContract | None:
    """Read the server-copied contract from a generic run's metadata."""
    if not isinstance(metadata, Mapping):
        return None
    try:
        return ScheduleCompletionContract.model_validate(metadata.get(COMPLETION_CONTRACT_KEY))
    except ValidationError:
        return None


def serialized_completion_contract(contract: ScheduleCompletionContract) -> dict[str, Any]:
    """Return a JSON-compatible declaration while retaining future extra keys."""
    serialized = contract.model_dump(mode="json")
    if contract.max_requests is None:
        serialized.pop("max_requests", None)
    if contract.max_total_tokens is None:
        serialized.pop("max_total_tokens", None)
    return serialized


def validate_completion_json(value: dict[str, Any] | None) -> dict[str, Any] | None:
    """Validate that completion evidence is JSON-compatible and within its byte budget."""
    if value is None:
        return None
    try:
        encoded = json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise ValueError("completion_json must contain JSON-compatible values") from exc
    if len(encoded) > MAX_COMPLETION_JSON_BYTES:
        raise ValueError(
            f"completion_json must not exceed {MAX_COMPLETION_JSON_BYTES} serialized bytes"
        )
    return value


def render_completion_contract_instructions(
    contract: ScheduleCompletionContract | None,
) -> str:
    """Render required completion criteria as a runtime system-instruction block."""
    if contract is None or not contract.required:
        return ""
    criteria = "\n".join(
        f"{index}. {criterion}" for index, criterion in enumerate(contract.criteria, start=1)
    )
    return (
        "## Completion Contract\n\n"
        f"Before finishing, call `{REPORT_COMPLETION_TOOL_NAME}` exactly once. Report `pass` only "
        "when every criterion below is satisfied; otherwise report `fail` and explain what remains.\n\n"
        f"{criteria}"
    )
