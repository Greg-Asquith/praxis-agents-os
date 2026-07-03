"""Runtime run envelope tests."""

import pytest

from models.agent_run import AgentRun
from services.agent_runs.domain import (
    RUN_TRIGGER_DELEGATED,
    RUN_TRIGGER_INTERACTIVE,
    RUN_TRIGGER_SCHEDULED,
)
from services.agents.runtime.envelope import build_run_envelope


@pytest.mark.parametrize(
    "trigger",
    [
        RUN_TRIGGER_INTERACTIVE,
        RUN_TRIGGER_SCHEDULED,
        RUN_TRIGGER_DELEGATED,
    ],
)
def test_build_run_envelope_uses_known_trigger_as_principal(trigger: str) -> None:
    envelope = build_run_envelope(AgentRun(trigger=trigger))

    assert envelope.principal == trigger
    assert envelope.side_effect_policy == "allow"
    assert envelope.max_delegation_depth == 1


def test_build_run_envelope_rejects_unknown_trigger() -> None:
    with pytest.raises(ValueError, match="Unsupported agent run trigger"):
        build_run_envelope(AgentRun(trigger="telepathy"))
