# apps/api/services/agents/runtime/lifespan.py

"""Runtime startup and shutdown hooks for agent execution."""

import logging

from core.database import configure_async_db_session, get_async_db_session_factory
from services.agent_runs import reap_abandoned_runs

logger = logging.getLogger(__name__)


async def sweep_abandoned_agent_runs_on_startup() -> None:
    """Fail stale non-terminal agent runs left behind by a prior process."""
    session_factory = get_async_db_session_factory()
    async with session_factory() as db:
        await configure_async_db_session(db)
        result = await reap_abandoned_runs(db)
        await db.commit()
        if result.failed_count:
            logger.warning(
                "Reaped abandoned agent runs on startup",
                extra={"failed_count": result.failed_count},
            )
