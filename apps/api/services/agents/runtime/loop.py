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
from services.agents.models import build_model, resolve_agent_model
from services.agents.models.domain import ResolvedModel
from services.agents.runtime.capabilities import build_runtime_capabilities
from services.agents.runtime.context import RuntimeDeps
from services.agents.runtime.delegation.tool_names import (
    DELEGATE_TO_AGENT_TOOL_NAME,
    LIST_DELEGATE_AGENTS_TOOL_NAME,
)
from services.agents.runtime.tools import build_runtime_tools

DELEGATION_INSTRUCTIONS = f"""\
You may delegate clearly bounded subtasks to other agents only when a listed
delegate is better suited than handling the work yourself.

Delegation rules:
- Call {LIST_DELEGATE_AGENTS_TOOL_NAME} before {DELEGATE_TO_AGENT_TOOL_NAME}.
- Use {DELEGATE_TO_AGENT_TOOL_NAME} only with an id returned by {LIST_DELEGATE_AGENTS_TOOL_NAME}.
- Give the delegate complete task instructions and relevant context.
- Treat the delegate result as supporting evidence; you remain responsible for
  the final answer to the user.
- If a delegated run needs approval, tell the user what is pending instead of
  retrying the same delegation.
"""


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
) -> RuntimeAgent:
    """Build a Pydantic AI agent for one Praxis agent configuration."""
    resolved_model = resolve_agent_model(agent)
    runtime_model = model or build_model(resolved_model)
    include_delegation = enable_delegation and (
        bool(delegate_agents) or force_delegation_tools
    )

    return RuntimeAgent(
        agent=PydanticAgent(
            runtime_model,
            name=_agent_name(agent),
            instructions=_runtime_instructions(
                agent,
                include_delegation=include_delegation,
            ),
            deps_type=RuntimeDeps,
            output_type=[str, DeferredToolRequests],
            tools=build_runtime_tools(agent, include_delegation=include_delegation),
            capabilities=build_runtime_capabilities(agent),
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


def _runtime_instructions(agent: Agent, *, include_delegation: bool) -> str:
    if not include_delegation:
        return agent.instructions
    return f"{agent.instructions.rstrip()}\n\n{DELEGATION_INSTRUCTIONS}"
