# apps/api/services/ai_usage/admit_platform_ingestion.py

"""Durable admission for bounded platform ingestion calls."""

from sqlalchemy import func
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import SESSION_MAINTENANCE_KEY, maintenance_async_db_session
from core.exceptions.auth import AuthorizationError
from core.exceptions.general import RateLimitError
from core.settings import settings
from models.platform_ingestion_usage import PlatformIngestionUsage
from services.embeddings.utils import current_period_month


async def admit_platform_ingestion(db: AsyncSession) -> None:
    """Reserves one monthly call before provider I/O, retaining failed attempts."""
    if not db.info.get(SESSION_MAINTENANCE_KEY):
        raise AuthorizationError("Platform ingestion requires a maintenance session")
    table = PlatformIngestionUsage.__table__
    statement = insert(table).values(period_month=current_period_month(), requests_reserved=1)
    statement = statement.on_conflict_do_update(
        index_elements=[table.c.period_month],
        set_={
            "requests_reserved": table.c.requests_reserved + 1,
            "updated_at": func.now(),
        },
        where=table.c.requests_reserved < settings.PLATFORM_INGESTION_MONTHLY_CALL_BUDGET,
    ).returning(table.c.requests_reserved)
    async with maintenance_async_db_session() as reservation_db:
        reserved = await reservation_db.scalar(statement)
        if reserved is None:
            raise RateLimitError("Platform knowledge ingestion has reached its monthly call budget")
