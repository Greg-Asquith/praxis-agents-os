"""Tests for agent schedule request schemas."""

from uuid import uuid4

import pytest
from pydantic import ValidationError

from models.agent import AgentScheduleRun
from services.agent_schedules.runs import schedule_health_from_run
from services.agent_schedules.schemas import AgentScheduleCreateRequest


@pytest.mark.parametrize(
    ("status", "outcome", "expected"),
    [
        ("running", None, "healthy"),
        ("completed", "success", "healthy"),
        ("completed", "gate_failed", "needs_attention"),
        ("completed", "budget_exhausted", "needs_attention"),
        ("retryable_failed", None, "retrying"),
        ("terminal_failed", None, "needs_attention"),
        ("cancelled", "cancelled", "cancelled"),
    ],
)
def test_schedule_status_and_outcome_boundaries_drive_health(
    status: str,
    outcome: str | None,
    expected: str,
) -> None:
    run = AgentScheduleRun(status=status)

    assert schedule_health_from_run(run, outcome=outcome) == expected


def _valid_payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "agent_id": uuid4(),
        "name": "Daily report",
        "schedule_type": "interval",
        "interval_minutes": 15,
        "default_prompt": "Run this.",
    }
    payload.update(overrides)
    return payload


def test_schedule_execution_params_rejects_deny_policy() -> None:
    with pytest.raises(ValidationError, match="side_effect_policy"):
        AgentScheduleCreateRequest.model_validate(
            _valid_payload(execution_params={"envelope": {"side_effect_policy": "deny"}})
        )
