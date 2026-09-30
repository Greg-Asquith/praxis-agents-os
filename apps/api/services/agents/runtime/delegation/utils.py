# apps/api/services/agents/runtime/delegation/utils.py

"""Helpers specific to runtime delegation."""

from uuid import UUID

from pydantic_ai import RunContext
from sqlalchemy import ColumnElement, select
from sqlalchemy.ext.asyncio import AsyncSession

from core.exceptions.general import NotFoundError
from models.agent import Agent
from models.workspace import Workspace
from services.agents.runtime.context import RuntimeDeps


async def load_caller_agent(
    db: AsyncSession,
    *,
    caller: Agent,
    workspace: Workspace,
) -> Agent:
    fresh_caller = await db.scalar(
        select(Agent).where(
            Agent.id == caller.id,
            Agent.workspace_id == workspace.id,
            Agent.deleted == False,  # noqa: E712
        )
    )
    if fresh_caller is None:
        raise NotFoundError(
            "Calling agent not found",
            resource_type="agent",
            resource_id=str(caller.id),
        )
    return fresh_caller


def visible_delegate_filters(caller: Agent, *, workspace: Workspace) -> list[ColumnElement[bool]]:
    """Return the SQL predicate for agents the freshly loaded caller may delegate to."""
    filters: list[ColumnElement[bool]] = [
        Agent.workspace_id == workspace.id,
        Agent.deleted == False,  # noqa: E712
        Agent.is_active.is_(True),
        Agent.id != caller.id,
    ]
    # The built-in agent may delegate to any other active agent in the workspace.
    if not caller.is_builtin:
        filters.append(Agent.id.in_(normalized_allowed_agent_ids(caller.allowed_agent_ids or [])))
    return filters


def normalized_allowed_agent_ids(raw: object) -> list[UUID]:
    if not isinstance(raw, list):
        return []

    normalized: list[UUID] = []
    seen: set[UUID] = set()
    for value in raw:
        try:
            agent_id = UUID(str(value))
        except (TypeError, ValueError):
            continue
        if agent_id in seen:
            continue
        normalized.append(agent_id)
        seen.add(agent_id)
    return normalized


def truncate(value: str, limit: int) -> tuple[str, bool]:
    if len(value) <= limit:
        return value, False
    return value[:limit], True


def safe_error(exc: Exception) -> str:
    message = " ".join(str(exc).split())
    if not message:
        message = exc.__class__.__name__
    if len(message) > 500:
        return f"{message[:500]}..."
    return message


def delegation_precheck_failure(
    ctx: RunContext[RuntimeDeps], *, task: str, subject: str
) -> str | None:
    """Return why a child run cannot start, or None when it can."""
    if not task:
        return f"{subject} must not be blank."
    if ctx.deps.envelope.max_delegation_depth > ctx.deps.delegation_depth:
        return None
    # An approved resume past the depth limit cannot return a plain failure.
    if ctx.tool_call_approved:
        from services.agent_runs.continuation_state import AgentRunResumeRequiresRecoveryError

        raise AgentRunResumeRequiresRecoveryError()
    return "Delegation depth limit reached."
