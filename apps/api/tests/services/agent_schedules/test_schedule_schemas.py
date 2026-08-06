"""Tests for agent schedule request schemas."""

from uuid import uuid4

import pytest
from pydantic import ValidationError

from models.agent import AgentScheduleRun
from services.agent_schedules.runs import schedule_health_from_run
from services.agent_schedules.schemas import AgentScheduleCreateRequest
from services.completion_contract import (
    MAX_COMPLETION_JSON_BYTES,
    validate_completion_json,
)


def test_completion_outcomes_drive_schedule_health() -> None:
    run = AgentScheduleRun(status="completed")

    assert schedule_health_from_run(run, outcome="success") == "healthy"
    assert schedule_health_from_run(run, outcome="gate_failed") == "needs_attention"
    assert schedule_health_from_run(run, outcome="budget_exhausted") == "needs_attention"


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


def test_schedule_name_is_required_normalized_text() -> None:
    schedule = AgentScheduleCreateRequest.model_validate(_valid_payload(name="  Daily report  "))
    assert schedule.name == "Daily report"

    with pytest.raises(ValidationError, match="name"):
        AgentScheduleCreateRequest.model_validate(_valid_payload(name="   "))

    payload_without_name = _valid_payload()
    del payload_without_name["name"]
    with pytest.raises(ValidationError, match="name"):
        AgentScheduleCreateRequest.model_validate(payload_without_name)


def test_schedule_execution_params_envelope_must_be_object() -> None:
    with pytest.raises(ValidationError):
        AgentScheduleCreateRequest.model_validate(
            _valid_payload(execution_params={"envelope": "allow"})
        )


def test_schedule_execution_params_rejects_deny_policy() -> None:
    with pytest.raises(ValidationError, match="side_effect_policy"):
        AgentScheduleCreateRequest.model_validate(
            _valid_payload(execution_params={"envelope": {"side_effect_policy": "deny"}})
        )


def test_schedule_execution_params_rejects_non_string_policy_with_validation_error() -> None:
    with pytest.raises(ValidationError):
        AgentScheduleCreateRequest.model_validate(
            _valid_payload(execution_params={"envelope": {"side_effect_policy": ["allow"]}})
        )


def test_schedule_completion_contract_normalizes_bounded_criteria() -> None:
    schedule = AgentScheduleCreateRequest.model_validate(
        _valid_payload(
            execution_params={
                "completion_contract": {
                    "required": True,
                    "criteria": ["  A report was created  ", "Every account was reviewed"],
                },
                "future_setting": True,
            }
        )
    )

    assert schedule.execution_params == {
        "completion_contract": {
            "required": True,
            "criteria": ["A report was created", "Every account was reviewed"],
        },
        "future_setting": True,
    }


@pytest.mark.parametrize(
    "contract",
    [
        {"required": True, "criteria": []},
        {"required": True, "criteria": ["x" * 501]},
        {"required": True, "criteria": [str(index) for index in range(21)]},
    ],
)
def test_schedule_completion_contract_rejects_invalid_criteria(contract: object) -> None:
    with pytest.raises(ValidationError, match="completion_contract"):
        AgentScheduleCreateRequest.model_validate(
            _valid_payload(execution_params={"completion_contract": contract})
        )


def test_completion_json_limit_accepts_largest_schema_valid_report() -> None:
    report = {
        "status": "pass",
        "summary": "\0" * 1000,
        "evidence": ["\0" * 500 for _ in range(20)],
    }

    assert validate_completion_json(report) is report
    assert MAX_COMPLETION_JSON_BYTES == 72 * 1024
