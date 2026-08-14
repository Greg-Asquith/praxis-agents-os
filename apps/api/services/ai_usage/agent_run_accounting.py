# apps/api/services/ai_usage/agent_run_accounting.py

"""Agent-run invocation usage accounting values."""

from dataclasses import dataclass
from datetime import datetime

from pydantic_ai.usage import RunUsage

from services.ai_usage.utils import usage_values


@dataclass(frozen=True, slots=True)
class AgentRunMeteringContext:
    """Invocation-local accounting around a possibly shared cumulative usage object."""

    invocation_started_at: datetime
    baseline: dict[str, int]
    usage: RunUsage
    provider: str
    model: str

    def accumulator_delta(self) -> dict[str, int]:
        current = usage_values(self.usage)
        return {name: max(0, value - self.baseline[name]) for name, value in current.items()}
