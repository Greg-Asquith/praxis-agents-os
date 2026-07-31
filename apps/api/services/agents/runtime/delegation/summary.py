# apps/api/services/agents/runtime/delegation/summary.py

"""Build model-facing delegate agent summaries."""

from models.agent import Agent
from services.agents.models import resolve_agent_model
from services.agents.models.domain import ModelConfigurationError
from services.agents.runtime.delegation.schemas import DelegateAgentSummary
from services.agents.runtime.entity_references.domain import AgentReference


def summarize_delegate_agent(agent: Agent) -> DelegateAgentSummary:
    try:
        model = resolve_agent_model(agent).qualified_id
    except ModelConfigurationError:
        model = None
    return DelegateAgentSummary(
        id=agent.id,
        slug=agent.slug,
        name=agent.name,
        description=agent.description,
        model=model,
        tool_count=len(agent.tool_names or []),
        skill_count=len(agent.skill_ids or []),
        reference=AgentReference(
            entity_id=agent.id,
            label=agent.name,
            description=(agent.description or "Delegate agent")[:1000],
        ),
    )
