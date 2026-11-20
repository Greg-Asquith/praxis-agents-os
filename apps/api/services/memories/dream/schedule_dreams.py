# apps/api/services/memories/dream/schedule_dreams.py

"""Start one dream for each learning workspace with conversations finished since its last dream."""

import logging
from datetime import datetime, timedelta

from sqlalchemy import exists, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from core.settings import settings
from models.agent_run import AgentRun
from models.conversation import CONVERSATION_SOURCE_DIRECT, Conversation
from models.memory_dream_run import MemoryDreamRun
from models.workspace import Workspace
from services.agent_runs.domain import RUN_STATUS_COMPLETED
from services.memories.dream.domain import (
    DREAM_ERROR_STALLED,
    DREAM_STATUS_COLLECTING,
    DREAM_STATUS_COMPLETED,
    DREAM_STATUS_FAILED,
    FINAL_DREAM_STATUSES,
)
from services.memories.dream.utils import enqueue_dream_step, move_dream_run

logger = logging.getLogger(__name__)


async def schedule_dreams(db: AsyncSession, *, now: datetime) -> int:
    """Creates and queues new dream runs, returning how many started. Runs as maintenance."""
    interval = timedelta(seconds=settings.MEMORY_DREAM_INTERVAL_SECONDS)
    await _fail_stalled_runs(db, before=now - interval, now=now)

    watermarks = (
        select(
            MemoryDreamRun.workspace_id,
            func.max(MemoryDreamRun.window_end).label("watermark"),
        )
        .where(MemoryDreamRun.status == DREAM_STATUS_COMPLETED)
        .group_by(MemoryDreamRun.workspace_id)
        .subquery()
    )
    # The first dream reads one interval back; it never backfills older conversations.
    window_start = func.coalesce(watermarks.c.watermark, now - interval)
    finished_since = exists().where(
        AgentRun.workspace_id == Workspace.id,
        AgentRun.status == RUN_STATUS_COMPLETED,
        AgentRun.deleted.is_(False),
        AgentRun.completed_at > window_start,
        AgentRun.completed_at <= now,
        Conversation.id == AgentRun.conversation_id,
        Conversation.source == CONVERSATION_SOURCE_DIRECT,
        Conversation.deleted.is_(False),
    )
    unfinished = select(MemoryDreamRun.workspace_id).where(
        MemoryDreamRun.status.not_in(FINAL_DREAM_STATUSES)
    )
    rows = (
        await db.execute(
            select(Workspace.id, watermarks.c.watermark)
            .outerjoin(watermarks, watermarks.c.workspace_id == Workspace.id)
            .where(
                Workspace.deleted.is_(False),
                Workspace.status == "active",
                Workspace.memory_learning_enabled.is_(True),
                Workspace.id.not_in(unfinished),
                # A repeated schedule pass inside one interval starts nothing new.
                func.coalesce(watermarks.c.watermark, now - interval) <= now - interval / 2,
                finished_since,
            )
            .order_by(Workspace.id)
        )
    ).all()
    for workspace_id, watermark in rows:
        run = MemoryDreamRun(
            workspace_id=workspace_id,
            status=DREAM_STATUS_COLLECTING,
            window_start=watermark or now - interval,
            window_end=now,
        )
        db.add(run)
        await db.flush()
        await enqueue_dream_step(db, run)
    return len(rows)


async def _fail_stalled_runs(db: AsyncSession, *, before: datetime, now: datetime) -> None:
    """Fails runs left unfinished for a whole interval, so a lost job can't block a workspace."""
    stalled = await db.scalars(
        select(MemoryDreamRun)
        .where(
            MemoryDreamRun.status.not_in(FINAL_DREAM_STATUSES),
            MemoryDreamRun.created_at < before,
        )
        .with_for_update(skip_locked=True)
    )
    for run in stalled:
        logger.warning("Failing a stalled dream run", extra={"dream_run_id": str(run.id)})
        move_dream_run(run, DREAM_STATUS_FAILED, now=now, error_code=DREAM_ERROR_STALLED)
    await db.flush()
