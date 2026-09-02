"""Tests for explicit model-facing approval denials."""

import pytest

from services.agent_runs.utils import denial_message_for_model


@pytest.mark.parametrize(
    ("reason", "expected"),
    [
        (
            "The budget is too high.",
            "The user declined this action, so it was not performed. "
            "Reason: The budget is too high.",
        ),
        (
            None,
            "The user declined this action, so it was not performed. No reason was given.",
        ),
    ],
)
def test_denial_message_for_model_frames_the_operator_decision(
    reason: str | None,
    expected: str,
) -> None:
    assert denial_message_for_model(reason) == expected
