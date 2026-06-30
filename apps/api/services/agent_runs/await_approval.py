# apps/api/services/agent_runs/await_approval.py

"""Suspend a run pending a human approval decision."""

from sqlalchemy.ext.asyncio import AsyncSession

from models.agent_run import AgentRun
from services.agent_runs.domain import RUN_STATUS_AWAITING_APPROVAL
from services.agent_runs.utils import transition_run_status


async def mark_run_awaiting_approval(db: AsyncSession, run: AgentRun) -> AgentRun:
    """Move a running run into awaiting_approval until a decision resumes it."""
    return await transition_run_status(db, run, RUN_STATUS_AWAITING_APPROVAL)
