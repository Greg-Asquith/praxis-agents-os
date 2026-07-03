# apps/api/services/agents/runtime/envelope.py

"""Server-minted execution grants for one runtime run."""

from dataclasses import dataclass
from typing import Literal, cast

from models.agent_run import AgentRun
from services.agent_runs.domain import (
    ALL_RUN_TRIGGERS,
)

RunPrincipal = Literal["interactive", "scheduled", "delegated"]
SideEffectPolicy = Literal["allow", "require_approval", "deny"]


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
    return RunEnvelope(principal=cast(RunPrincipal, run.trigger))
