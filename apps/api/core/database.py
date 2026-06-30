# apps/api/core/database.py

"""Async SQLAlchemy engine and session management."""

import logging
from collections.abc import AsyncGenerator

from fastapi import Request
from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool

from core.exceptions.database import DatabaseError
from core.settings import settings

logger = logging.getLogger(__name__)

_async_engine: AsyncEngine | None = None
_async_session_factory: async_sessionmaker[AsyncSession] | None = None

# Recycle pooled connections after one hour to avoid stale server-side timeouts.
_POOL_RECYCLE_SECONDS = 3600


def get_async_engine() -> AsyncEngine:
    """Get or create the process-wide async database engine."""
    global _async_engine

    if _async_engine is None:
        engine_kwargs: dict[str, object] = {
            "pool_pre_ping": True,
            "pool_recycle": _POOL_RECYCLE_SECONDS,
            "echo": settings.SQL_DEBUG,
            "echo_pool": "debug" if settings.SQL_DEBUG else False,
        }
        # NullPool only for local debugging; production must keep a sized pool.
        if settings.DEBUG and settings.is_dev:
            engine_kwargs["poolclass"] = NullPool
        else:
            engine_kwargs["pool_size"] = settings.DB_POOL_SIZE
            engine_kwargs["max_overflow"] = settings.DB_POOL_MAX_OVERFLOW

        _async_engine = create_async_engine(settings.DATABASE_URL, **engine_kwargs)

    return _async_engine


def get_async_db_session_factory() -> async_sessionmaker[AsyncSession]:
    """Get or create the process-wide async session factory."""
    global _async_session_factory

    if _async_session_factory is None:
        _async_session_factory = async_sessionmaker(
            get_async_engine(),
            class_=AsyncSession,
            expire_on_commit=False,
        )

    return _async_session_factory


async def configure_async_db_session(session: AsyncSession) -> None:
    """Apply per-session database settings used by request and fallback sessions."""
    # PostgreSQL SET statements do not accept bind parameters for configuration values, so interpolate the validated integer setting directly.
    await session.execute(
        text(f"SET ivfflat.probes = {settings.IVFFLAT_PROBES}"),
    )


async def get_async_db_session(request: Request) -> AsyncGenerator[AsyncSession]:
    """FastAPI dependency that yields an async database session."""
    existing_session = getattr(request.state, "db", None)
    if existing_session is not None:
        yield existing_session
        return

    session_factory = get_async_db_session_factory()
    session = session_factory()

    await configure_async_db_session(session)

    try:
        yield session
    except Exception:
        await session.rollback()
        raise
    else:
        try:
            await session.commit()
        except Exception:
            await session.rollback()
            raise
    finally:
        await session.close()


async def close_db_connections() -> None:
    """Dispose database connections and reset cached factories."""
    global _async_engine, _async_session_factory

    if _async_engine is not None:
        await _async_engine.dispose()
        _async_engine = None
        _async_session_factory = None


async def check_database_connection() -> None:
    """Verify the database accepts a simple query, raising on failure."""
    try:
        session_factory = get_async_db_session_factory()
        async with session_factory() as session:
            await session.execute(text("SELECT 1"))
    except Exception as exc:
        raise DatabaseError(
            "Database connection check failed",
            details={"error": str(exc), "error_type": type(exc).__name__},
        ) from exc
