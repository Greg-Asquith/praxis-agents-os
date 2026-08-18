# apps/api/services/agents/runtime/context.py

"""Typed dependencies passed into Pydantic AI runtime tools and hooks."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from sqlalchemy.ext.asyncio import AsyncSession

from models.agent import Agent
from models.agent_run import AgentRun
from models.conversation import Conversation
from models.user import User
from models.workspace import Workspace, WorkspaceMembership
from services.agents.runtime.envelope import RunEnvelope
from services.agents.runtime.sinks import EventSink

if TYPE_CHECKING:
    from services.agents.runtime.tools.contract import RuntimeToolDefinition
    from services.integrations.context.domain import ResolvedActiveContext


@dataclass(frozen=True)
class RuntimeDeps:
    """Application state available to runtime tools and capabilities."""

    db: AsyncSession
    user: User
    workspace: Workspace
    membership: WorkspaceMembership
    conversation: Conversation
    agent: Agent
    run: AgentRun
    sink: EventSink
    envelope: RunEnvelope
    delegation_depth: int = 0
    active_context: ResolvedActiveContext | None = None
    workspace_tool_definitions: tuple[RuntimeToolDefinition, ...] = ()
