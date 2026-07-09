# apps/api/services/agents/runtime/delegation/utils.py

"""Helpers specific to runtime delegation."""

import asyncio
import os
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.exceptions.general import NotFoundError
from models.agent import Agent
from models.workspace import Workspace


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


def owner_instance_id() -> str:
    return f"{os.uname().nodename}:{os.getpid()}"


async def heartbeat(
    run_id: UUID,
    owner_instance_id: str,
    stop: asyncio.Event,
    cancel_target: asyncio.Task | None = None,
) -> None:
    from services.agents.runtime.heartbeat import heartbeat_agent_run_lease

    await heartbeat_agent_run_lease(
        run_id=run_id,
        owner_instance_id=owner_instance_id,
        stop=stop,
        cancel_target=cancel_target,
    )
