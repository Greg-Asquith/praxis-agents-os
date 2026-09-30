# apps/api/services/agents/runtime/subagents/build_subagent.py

"""Build the transient, unsaved agent a sub-agent run executes as."""

from models.agent import Agent
from models.agent_run import AgentRun
from models.workspace import Workspace
from services.agents.models.domain import PROVIDER_AZURE
from services.agents.models.resolution import effective_model_pair
from services.agents.runtime.subagents.constants import SUBAGENT_METADATA_KEY
from services.agents.runtime.subagents.spec import SubagentSpec, subagent_spec_from_metadata


def build_subagent(parent: Agent, spec: SubagentSpec, *, workspace: Workspace | None) -> Agent:
    """Return an unsaved agent with the parent's identity and tools, never more.

    It keeps the parent's id so memory reads, audit, and ownership checks use
    the parent. Tool selection and policies copy the live parent row, so a
    resumed sub-agent loses anything the parent lost. Delegation, sub-agents,
    and memory writes are removed by the runtime, not by this row.
    """
    same_model = effective_model_pair(parent, workspace=workspace) == (
        spec.model_provider,
        spec.model,
    )
    return Agent(
        id=parent.id,
        workspace_id=parent.workspace_id,
        created_by=parent.created_by,
        custom_name=spec.role,
        slug=parent.slug,
        instructions=spec.instructions,
        tool_names=list(parent.tool_names or []),
        all_tools=bool(parent.all_tools),
        excluded_tool_names=list(parent.excluded_tool_names or []),
        tool_policies=dict(parent.tool_policies or {}) or None,
        allowed_agent_ids=[],
        subagents_enabled=False,
        # Unsaved rows get no column defaults, and the built-in identity must not apply.
        is_builtin=False,
        is_active=True,
        deleted=False,
        model_provider=spec.model_provider,
        model=spec.model,
        # Provider-specific settings only carry over when the model is unchanged.
        model_settings=parent.model_settings if same_model else None,
        azure_deployment=parent.azure_deployment if spec.model_provider == PROVIDER_AZURE else None,
        max_steps=parent.max_steps,
        metadata_json={
            **(parent.metadata_json or {}),
            SUBAGENT_METADATA_KEY: spec.model_dump(mode="json"),
        },
    )


def runtime_agent_for_run(run: AgentRun, agent: Agent, *, workspace: Workspace | None) -> Agent:
    """Return the agent a run executes as: its saved row, or the sub-agent built from it."""
    spec = subagent_spec_from_metadata(run.metadata_json)
    return agent if spec is None else build_subagent(agent, spec, workspace=workspace)


def is_subagent(agent: Agent) -> bool:
    """Return whether this agent is a transient sub-agent."""
    return subagent_spec_from_metadata(agent.metadata_json) is not None
