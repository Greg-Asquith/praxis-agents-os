# apps/api/services/agents/runtime/loop.py

"""Construct the Pydantic AI agent used by one Praxis runtime turn."""

import re
from dataclasses import dataclass

from pydantic_ai import Agent as PydanticAgent
from pydantic_ai.models import Model
from pydantic_ai.usage import UsageLimits
from sqlalchemy.ext.asyncio import AsyncSession

from models.agent import Agent
from models.agent_run import AgentRun
from models.conversation import Conversation
from services.agents.models import build_model, resolve_agent_model
from services.agents.models.domain import ResolvedModel
from services.agents.runtime.sinks import EventSink


@dataclass(frozen=True)
class RuntimeDeps:
    """Application state made available to future runtime tools."""

    db: AsyncSession
    conversation: Conversation
    agent: Agent
    run: AgentRun
    sink: EventSink


@dataclass(frozen=True)
class RuntimeAgent:
    """The constructed Pydantic AI agent and the resolved limits behind it."""

    agent: PydanticAgent[RuntimeDeps, str]
    resolved_model: ResolvedModel
    usage_limits: UsageLimits


def build_runtime_agent(
    agent: Agent,
    *,
    model: Model | None = None,
) -> RuntimeAgent:
    """Build a Pydantic AI agent for one Praxis agent configuration."""
    resolved_model = resolve_agent_model(agent)
    runtime_model = model or build_model(resolved_model)

    return RuntimeAgent(
        agent=PydanticAgent(
            runtime_model,
            name=_agent_name(agent),
            instructions=agent.instructions,
            deps_type=RuntimeDeps,
            output_type=str,
        ),
        resolved_model=resolved_model,
        usage_limits=UsageLimits(request_limit=resolved_model.max_steps),
    )


def _agent_name(agent: Agent) -> str:
    slug = agent.slug or str(agent.id)
    safe_slug = re.sub(r"[^0-9A-Za-z_]+", "_", slug).strip("_")
    return f"praxis_agent_{safe_slug or 'unnamed'}"
