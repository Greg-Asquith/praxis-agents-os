"""Builds local execution handles for tests without a database admission."""

import asyncio
from uuid import UUID, uuid4

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
