# apps/api/services/agents/runtime/loop.py

"""Construct the Pydantic AI agent used by one Praxis runtime turn."""

import re
from collections.abc import Sequence
from dataclasses import dataclass

from pydantic_ai import Agent as PydanticAgent, DeferredToolRequests
from pydantic_ai.models import Model
from pydantic_ai.usage import UsageLimits

from core.settings import settings
from models.agent import Agent
from models.skills import Skill
from services.agents.models import build_model, resolve_agent_model
from services.agents.models.domain import ResolvedModel
from services.agents.runtime.capabilities import build_runtime_capabilities
from services.agents.runtime.context import RuntimeDeps
from services.agents.runtime.load_context import AvailableFile
from services.agents.runtime.prompt import (
    build_system_prompt,
    runtime_prompt_blocks,
)
from services.agents.runtime.skills import build_skill_capabilities
from services.agents.runtime.tools import (
    build_runtime_native_capabilities,
    build_runtime_tools,
)


@dataclass(frozen=True)
class RuntimeAgent:
    """The constructed Pydantic AI agent and the resolved limits behind it."""

    agent: PydanticAgent[RuntimeDeps, str | DeferredToolRequests]
    resolved_model: ResolvedModel
    usage_limits: UsageLimits


def build_runtime_agent(
    agent: Agent,
    *,
    model: Model | None = None,
    delegate_agents: Sequence[Agent] = (),
    enable_delegation: bool = True,
    force_delegation_tools: bool = False,
    skills: Sequence[Skill] = (),
    available_files: Sequence[AvailableFile] = (),
    skipped_tool_names: list[str] | None = None,
) -> RuntimeAgent:
    """Build a Pydantic AI agent for one Praxis agent configuration."""
    resolved_model = resolve_agent_model(agent)
    runtime_model = model or build_model(resolved_model)
    include_delegation = enable_delegation and (bool(delegate_agents) or force_delegation_tools)

    return RuntimeAgent(
        agent=PydanticAgent(
            runtime_model,
            name=_agent_name(agent),
            instructions=_runtime_instructions(
                agent,
                include_delegation=include_delegation,
                available_files=available_files,
            ),
            deps_type=RuntimeDeps,
            output_type=[str, DeferredToolRequests],
            tools=build_runtime_tools(
                agent,
                include_delegation=include_delegation,
                skipped_tool_names=skipped_tool_names,
            ),
            capabilities=[
                *build_runtime_capabilities(agent),
                *build_runtime_native_capabilities(agent, resolved_model),
                *build_skill_capabilities(skills),
            ],
        ),
        resolved_model=resolved_model,
        usage_limits=UsageLimits(
            request_limit=resolved_model.max_steps,
            total_tokens_limit=settings.AGENT_RUN_TOTAL_TOKENS_LIMIT,
        ),
    )


def _agent_name(agent: Agent) -> str:
    slug = agent.slug or str(agent.id)
    safe_slug = re.sub(r"[^0-9A-Za-z_]+", "_", slug).strip("_")
    return f"praxis_agent_{safe_slug or 'unnamed'}"


def _runtime_instructions(
    agent: Agent,
    *,
    include_delegation: bool,
    available_files: Sequence[AvailableFile] = (),
) -> str:
    return build_system_prompt(
        runtime_prompt_blocks(
            agent,
            include_delegation=include_delegation,
            available_files=available_files,
        )
    )
