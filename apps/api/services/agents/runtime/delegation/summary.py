# apps/api/services/agents/runtime/delegation/summary.py

"""Build model-facing delegate agent summaries."""

from collections.abc import Sequence
from typing import TYPE_CHECKING

from models.agent import Agent
from models.workspace import Workspace
from services.agents.models import resolve_agent_model
from services.agents.models.domain import ModelConfigurationError
from services.agents.runtime.delegation.schemas import DelegateAgentSummary
from services.agents.runtime.entity_references.domain import AgentReference

if TYPE_CHECKING:
    from services.agents.runtime.tools.contract import RuntimeToolDefinition


def summarize_delegate_agent(
    agent: Agent,
    *,
    workspace: Workspace,
    workspace_definitions: Sequence["RuntimeToolDefinition"] = (),
) -> DelegateAgentSummary:
    # The registry imports the delegation tools, which import this module.
    from services.agents.runtime.tools.registry import resolve_selected_tool_names

    try:
        model = resolve_agent_model(agent, workspace=workspace).qualified_id
    except ModelConfigurationError:
        model = None
    return DelegateAgentSummary(
        id=agent.id,
        slug=agent.slug,
        name=agent.name,
        description=agent.description,
        model=model,
        tool_count=len(resolve_selected_tool_names(agent, workspace_definitions)),
        reference=AgentReference(
            entity_id=agent.id,
            label=agent.name,
            description=(agent.description or "Delegate agent")[:1000],
        ),
    )
