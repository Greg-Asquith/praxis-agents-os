# apps/api/services/agents/runtime/context.py

"""Typed dependencies passed into Pydantic AI runtime tools and hooks."""

from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from models.agent import Agent
from models.agent_run import AgentRun
from models.conversation import Conversation
from models.user import User
from models.workspace import Workspace
from services.agents.runtime.sinks import EventSink


@dataclass(frozen=True)
class RuntimeDeps:
    """Application state available to runtime tools and capabilities."""

    db: AsyncSession
    user: User
    workspace: Workspace
    conversation: Conversation
    agent: Agent
    run: AgentRun
    sink: EventSink
    delegation_depth: int = 0
