# apps/api/services/ai_usage/agent_run_accounting.py

"""Invocation usage attribution independent of ledger commit order."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from uuid import UUID, uuid4, uuid5

from pydantic_ai.usage import RunUsage

from models.agent_run import AgentRun
from services.ai_usage.domain import PURPOSE_AGENT_RUN, AIUsageEventData
from services.ai_usage.utils import usage_values


@dataclass(slots=True)
class AgentRunMeteringContext:
    """Captures each invocation before its awaited finalisation begins."""

    baseline: dict[str, int]
    usage: RunUsage
    provider: str
    model: str
    invocation_id: UUID = field(default_factory=uuid4)
    parent: AgentRunMeteringContext | None = None
    _children: dict[str, int] = field(default_factory=dict, init=False)
    _own: dict[str, int] | None = field(default=None, init=False)
    _event: AIUsageEventData | None = field(default=None, init=False)

    def freeze(self) -> dict[str, int]:
        """Freezes usage and attributes the whole child interval to its parent once."""
        if self._own is None:
            delta = {
                name: max(0, value - self.baseline[name])
                for name, value in usage_values(self.usage).items()
            }
            self._own = {
                name: max(0, value - self._children.get(name, 0)) for name, value in delta.items()
            }
            if self.parent is not None:
                for name, value in delta.items():
                    self.parent._children[name] = self.parent._children.get(name, 0) + value
        return dict(self._own)

    def capture_run(self, run: AgentRun) -> None:
        """Captures attribution before cancellation can expire the ORM objects."""
        if self._event is not None:
            return
        self._event = AIUsageEventData(
            event_id=uuid5(run.id, f"{self.invocation_id}:{PURPOSE_AGENT_RUN}"),
            workspace_id=run.workspace_id,
            provider=self.provider,
            model=self.model,
            purpose=PURPOSE_AGENT_RUN,
            agent_id=run.agent_id,
            user_id=run.user_id,
            run_id=run.id,
            conversation_id=run.conversation_id,
            details={
                "usage_source": "accumulator_delta",
                "invocation_id": str(self.invocation_id),
            },
        )

    def event(self, run: AgentRun | None = None) -> AIUsageEventData:
        """Returns the same ledger identity and own usage on every settlement attempt."""
        if run is not None:
            self.capture_run(run)
        if self._event is None:
            raise RuntimeError("Invocation attribution has not been captured")
        return replace(self._event, **self.freeze())
