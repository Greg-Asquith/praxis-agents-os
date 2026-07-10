# apps/api/services/agents/runtime/envelope.py

"""Server-minted execution grants for one runtime run."""

from dataclasses import dataclass
from typing import Literal, cast

from pydantic import BaseModel, ConfigDict, ValidationError

from core.settings import settings
from models.agent_run import AgentRun
from services.agent_runs.domain import (
    ALL_RUN_TRIGGERS,
    RUN_TRIGGER_DELEGATED,
    RUN_TRIGGER_INTERACTIVE,
    RUN_TRIGGER_SCHEDULED,
)

RunPrincipal = Literal["interactive", "scheduled", "delegated"]
SideEffectPolicy = Literal["allow", "require_approval", "deny"]
_POLICY_RANK: dict[str, int] = {"allow": 0, "require_approval": 1, "deny": 2}


class _EnvelopeMetadata(BaseModel):
    side_effect_policy: SideEffectPolicy | None = None

    model_config = ConfigDict(extra="ignore")


class _RunMetadata(BaseModel):
    envelope: _EnvelopeMetadata | None = None

    model_config = ConfigDict(extra="ignore")


@dataclass(frozen=True)
class RunEnvelope:
    """Execution grant derived from persisted server state, never client input."""

    principal: RunPrincipal
    side_effect_policy: SideEffectPolicy = "allow"
    max_delegation_depth: int = 1


def build_run_envelope(run: AgentRun) -> RunEnvelope:
    """Build the explicit run envelope for one persisted agent run."""
    if run.trigger not in ALL_RUN_TRIGGERS:
        raise ValueError(f"Unsupported agent run trigger: {run.trigger!r}")
    principal = cast(RunPrincipal, run.trigger)
    return RunEnvelope(
        principal=principal,
        side_effect_policy=_side_effect_policy_for_run(run),
        max_delegation_depth=settings.AGENT_MAX_DELEGATION_DEPTH,
    )


def _side_effect_policy_for_run(run: AgentRun) -> SideEffectPolicy:
    if run.trigger == RUN_TRIGGER_INTERACTIVE:
        return "allow"
    if run.trigger == RUN_TRIGGER_SCHEDULED:
        configured = _policy_from_metadata(run.metadata_json)
        if configured is not None:
            return configured
        return settings.AGENT_SCHEDULED_SIDE_EFFECT_POLICY
    if run.trigger == RUN_TRIGGER_DELEGATED:
        inherited = _policy_from_metadata(run.metadata_json)
        if inherited is not None:
            return inherited
        return _most_restrictive_policy("allow", settings.AGENT_SCHEDULED_SIDE_EFFECT_POLICY)
    raise ValueError(f"Unsupported agent run trigger: {run.trigger!r}")


def _policy_from_metadata(metadata: object) -> SideEffectPolicy | None:
    try:
        parsed = _RunMetadata.model_validate(metadata or {})
    except ValidationError:
        return None
    if parsed.envelope is None:
        return None
    return parsed.envelope.side_effect_policy


def _most_restrictive_policy(*policies: SideEffectPolicy) -> SideEffectPolicy:
    return max(policies, key=lambda policy: _POLICY_RANK[policy])
