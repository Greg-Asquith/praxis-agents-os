"""Builds local execution handles for tests without a database admission."""

import asyncio
from collections.abc import Awaitable, Callable, Sequence
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from models.agent_run import AgentRun
from services.agents.runtime.execution_control import ExecutionControl


def build_execution_control(
    *, run_id: UUID | None = None, workspace_id: UUID | None = None, user_id: UUID | None = None
) -> ExecutionControl:
    now = asyncio.get_running_loop().time()
    return ExecutionControl(
        run_id=run_id or uuid4(),
        workspace_id=workspace_id or uuid4(),
        user_id=user_id or uuid4(),
        owner_instance_id=str(uuid4()),
        deadline=now + 1200,
        lease_deadline=now + 90,
    )


async def race_with_first_lock(
    factory: async_sessionmaker[AsyncSession],
    *,
    run_id: UUID,
    operations: Sequence[Callable[[AsyncSession], Awaitable[object]]],
    first: int,
) -> list[object]:
    """Runs independent transactions with an explicit first root-lock holder."""
    ready = asyncio.Barrier(len(operations))

    async def run(index, operation):
        async with factory() as db:
            if index == first:
                await db.scalar(select(AgentRun).where(AgentRun.id == run_id).with_for_update())
            await ready.wait()
            result = await operation(db)
            await db.commit()
            return result

    tasks = [asyncio.create_task(run(index, op)) for index, op in enumerate(operations)]
    try:
        return await asyncio.wait_for(asyncio.gather(*tasks), timeout=10)
    finally:
        for task in tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
