# apps/api/services/agents/runtime/loop.py

"""Construct the Pydantic AI agent used by one Praxis runtime turn."""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING

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

if TYPE_CHECKING:
    from services.integrations.context.domain import ResolvedActiveContext


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
    active_context: ResolvedActiveContext | None = None,
    skipped_tool_names: list[str] | None = None,
    workspace: object | None = None,
    disabled_tool_names: frozenset[str] = frozenset(),
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
                active_context=active_context,
            ),
            deps_type=RuntimeDeps,
            output_type=[str, DeferredToolRequests],
            tools=build_runtime_tools(
                agent,
                include_delegation=include_delegation,
                active_context=active_context,
                skipped_tool_names=skipped_tool_names,
                workspace=workspace,
                disabled_tool_names=disabled_tool_names,
            ),
            capabilities=[
                *build_runtime_capabilities(agent),
                *build_runtime_native_capabilities(
                    agent,
                    resolved_model,
                    workspace=workspace,
                    disabled_tool_names=disabled_tool_names,
                ),
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
    active_context: ResolvedActiveContext | None = None,
) -> str:
    from services.integrations.context.prompt_block import render_active_context_block

    return build_system_prompt(
        runtime_prompt_blocks(
            agent,
            include_delegation=include_delegation,
            available_files=available_files,
            active_context_block=(
                render_active_context_block(active_context) if active_context is not None else ""
            ),
        )
    )
