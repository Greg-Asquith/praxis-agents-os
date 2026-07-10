"""Runtime run envelope tests."""

import pytest

from core.settings import settings
from models.agent_run import AgentRun
from services.agent_runs.domain import (
    RUN_TRIGGER_DELEGATED,
    RUN_TRIGGER_INTERACTIVE,
    RUN_TRIGGER_SCHEDULED,
)
from services.agents.runtime.envelope import build_run_envelope


def test_build_run_envelope_allows_interactive_runs(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "AGENT_MAX_DELEGATION_DEPTH", 3)

    envelope = build_run_envelope(AgentRun(trigger=RUN_TRIGGER_INTERACTIVE))

    assert envelope.principal == RUN_TRIGGER_INTERACTIVE
    assert envelope.side_effect_policy == "allow"
    assert envelope.max_delegation_depth == 3


@pytest.mark.parametrize("policy", ["allow", "require_approval", "deny"])
def test_build_run_envelope_uses_scheduled_policy_setting(
    policy: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "AGENT_SCHEDULED_SIDE_EFFECT_POLICY", policy)

    envelope = build_run_envelope(AgentRun(trigger=RUN_TRIGGER_SCHEDULED))

    assert envelope.principal == RUN_TRIGGER_SCHEDULED
    assert envelope.side_effect_policy == policy


def test_build_run_envelope_uses_scheduled_policy_metadata(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "AGENT_SCHEDULED_SIDE_EFFECT_POLICY", "deny")

    envelope = build_run_envelope(
        AgentRun(
            trigger=RUN_TRIGGER_SCHEDULED,
            metadata_json={"envelope": {"side_effect_policy": "allow"}},
        )
    )

    assert envelope.side_effect_policy == "allow"


@pytest.mark.parametrize("policy", ["allow", "require_approval", "deny"])
def test_build_run_envelope_uses_delegated_policy_metadata(policy: str) -> None:
    envelope = build_run_envelope(
        AgentRun(
            trigger=RUN_TRIGGER_DELEGATED,
            metadata_json={"envelope": {"side_effect_policy": policy}},
        )
    )

    assert envelope.principal == RUN_TRIGGER_DELEGATED
    assert envelope.side_effect_policy == policy


def test_build_run_envelope_falls_back_for_legacy_delegated_runs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "AGENT_SCHEDULED_SIDE_EFFECT_POLICY", "deny")

    envelope = build_run_envelope(AgentRun(trigger=RUN_TRIGGER_DELEGATED))

    assert envelope.principal == RUN_TRIGGER_DELEGATED
    assert envelope.side_effect_policy == "deny"


def test_build_run_envelope_ignores_invalid_delegated_metadata(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "AGENT_SCHEDULED_SIDE_EFFECT_POLICY", "require_approval")

    envelope = build_run_envelope(
        AgentRun(
            trigger=RUN_TRIGGER_DELEGATED,
            metadata_json={"envelope": {"side_effect_policy": "root"}},
        )
    )

    assert envelope.side_effect_policy == "require_approval"


def test_build_run_envelope_ignores_non_string_policy_metadata(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "AGENT_SCHEDULED_SIDE_EFFECT_POLICY", "deny")

    envelope = build_run_envelope(
        AgentRun(
            trigger=RUN_TRIGGER_SCHEDULED,
            metadata_json={"envelope": {"side_effect_policy": ["allow"]}},
        )
    )

    assert envelope.side_effect_policy == "deny"


def test_build_run_envelope_rejects_unknown_trigger() -> None:
    with pytest.raises(ValueError, match="Unsupported agent run trigger"):
        build_run_envelope(AgentRun(trigger="telepathy"))
