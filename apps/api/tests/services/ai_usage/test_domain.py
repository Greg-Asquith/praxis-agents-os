"""Closed AI usage domain and model alignment tests."""

import re
from uuid import uuid4

import pytest

from models.ai_usage_event import AIUsageEvent
from services.ai_usage.domain import AI_USAGE_PURPOSES, AIUsageEventData


def _event(**overrides) -> AIUsageEventData:
    values = {
        "workspace_id": uuid4(),
        "provider": "openai",
        "model": "gpt-5.6-luna",
        "purpose": "agent_run",
    }
    values.update(overrides)
    return AIUsageEventData(**values)


@pytest.mark.parametrize(
    "overrides",
    [
        {"purpose": "unknown"},
        {"provider": " "},
        {"model": ""},
        {"input_tokens": -1},
        {"requests": True},
    ],
)
def test_invalid_event_values_fail_closed(overrides: dict[str, object]) -> None:
    with pytest.raises(ValueError):
        _event(**overrides)


def test_details_must_be_json_serializable_and_bounded() -> None:
    with pytest.raises(ValueError, match="JSON serializable"):
        _event(details={"bad": object()})

    with pytest.raises(ValueError, match="4096-byte"):
        _event(details={"value": "x" * 4097})


def test_model_purpose_check_matches_canonical_domain() -> None:
    constraint = next(
        item
        for item in AIUsageEvent.__table__.constraints
        if item.name == "ai_usage_events_purpose_check"
    )
    assert set(re.findall(r"'([^']+)'", str(constraint.sqltext))) == set(AI_USAGE_PURPOSES)


def test_zero_usage_is_not_metered() -> None:
    assert _event().is_zero
    assert not _event(requests=1).is_zero
