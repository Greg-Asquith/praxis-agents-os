# apps/api/core/database.py

"""Async SQLAlchemy engine and session management."""

import logging
from collections.abc import AsyncGenerator
from uuid import UUID

from fastapi import Request
from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import Session
from sqlalchemy.pool import NullPool

from core.exceptions.database import DatabaseError
from core.settings import settings

logger = logging.getLogger(__name__)

_async_engine: AsyncEngine | None = None
_async_session_factory: async_sessionmaker[AsyncSession] | None = None
_maintenance_async_engine: AsyncEngine | None = None
_maintenance_async_session_factory: async_sessionmaker[AsyncSession] | None = None

SESSION_WORKSPACE_ID_KEY = "praxis_workspace_id"
SESSION_USER_ID_KEY = "praxis_user_id"
SESSION_MAINTENANCE_KEY = "praxis_maintenance"
_RUNTIME_DATABASE_ROLE = "praxis_app"

# Recycle pooled connections after one hour to avoid stale server-side timeouts.
_POOL_RECYCLE_SECONDS = 3600


def _engine_kwargs() -> dict[str, object]:
    engine_kwargs: dict[str, object] = {
        "pool_pre_ping": True,
        "pool_recycle": _POOL_RECYCLE_SECONDS,
        "echo": settings.SQL_DEBUG,
        "echo_pool": "debug" if settings.SQL_DEBUG else False,
    }
    if settings.DEBUG and settings.is_dev:
        engine_kwargs["poolclass"] = NullPool
    else:
        engine_kwargs["pool_size"] = settings.DB_POOL_SIZE
        engine_kwargs["max_overflow"] = settings.DB_POOL_MAX_OVERFLOW
    return engine_kwargs


def get_async_engine() -> AsyncEngine:
    """Get or create the process-wide async database engine."""
    global _async_engine

    if _async_engine is None:
        _async_engine = create_async_engine(settings.DATABASE_URL, **_engine_kwargs())

    return _async_engine


def get_maintenance_async_engine() -> AsyncEngine:
    """Get or create the owning engine for migrations and cross-workspace work."""
    global _maintenance_async_engine

    if _maintenance_async_engine is None:
        _maintenance_async_engine = create_async_engine(
            settings.maintenance_database_url,
            **_engine_kwargs(),
        )
    return _maintenance_async_engine


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


def get_maintenance_async_db_session_factory() -> async_sessionmaker[AsyncSession]:
    """Get the owning session factory for deliberate cross-workspace operations."""
    global _maintenance_async_session_factory

    if _maintenance_async_session_factory is None:
        _maintenance_async_session_factory = async_sessionmaker(
            get_maintenance_async_engine(),
            class_=AsyncSession,
            expire_on_commit=False,
            info={SESSION_MAINTENANCE_KEY: True},
        )
    return _maintenance_async_session_factory


def _apply_transaction_context(
    session: Session,
    _transaction: object,
    connection,
) -> None:
    """Apply the runtime role and fail-closed tenant GUCs to every transaction."""
    if session.info.get(SESSION_MAINTENANCE_KEY):
        connection.execute(text("RESET ROLE"))
        return

    connection.execute(text(f"SET LOCAL ROLE {_RUNTIME_DATABASE_ROLE}"))
    for info_key, guc_name in (
        (SESSION_WORKSPACE_ID_KEY, "app.current_workspace_id"),
        (SESSION_USER_ID_KEY, "app.current_user_id"),
    ):
        value = session.info.get(info_key)
        if value is not None:
            connection.execute(
                text("SELECT set_config(:name, :value, true)"),
                {"name": guc_name, "value": str(value)},
            )


event.listen(Session, "after_begin", _apply_transaction_context)


async def set_session_tenant_context(
    session: AsyncSession,
    *,
    workspace_id: UUID | None = None,
    user_id: UUID | None = None,
) -> None:
    """Persist tenant context and apply it to the current transaction immediately."""
    updates: list[tuple[str, str, UUID]] = []
    if workspace_id is not None:
        updates.append((SESSION_WORKSPACE_ID_KEY, "app.current_workspace_id", workspace_id))
    if user_id is not None:
        updates.append((SESSION_USER_ID_KEY, "app.current_user_id", user_id))

    for info_key, _guc_name, value in updates:
        session.info[info_key] = value

    if session.in_transaction():
        for _info_key, guc_name, value in updates:
            await session.execute(
                text("SELECT set_config(:name, :value, true)"),
                {"name": guc_name, "value": str(value)},
            )


async def inherit_session_tenant_context(
    target: AsyncSession,
    source: AsyncSession,
) -> None:
    """Copy the established tenant context into an isolated runtime session."""
    await set_session_tenant_context(
        target,
        workspace_id=source.info.get(SESSION_WORKSPACE_ID_KEY),
        user_id=source.info.get(SESSION_USER_ID_KEY),
    )


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


async def get_maintenance_async_db_session() -> AsyncGenerator[AsyncSession]:
    """Yield a deliberate cross-workspace session for capability lookups."""
    session_factory = get_maintenance_async_db_session_factory()
    async with session_factory() as session:
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


async def close_db_connections() -> None:
    """Dispose database connections and reset cached factories."""
    global _async_engine, _async_session_factory
    global _maintenance_async_engine, _maintenance_async_session_factory

    if _async_engine is not None:
        await _async_engine.dispose()
        _async_engine = None
        _async_session_factory = None
    if _maintenance_async_engine is not None:
        await _maintenance_async_engine.dispose()
        _maintenance_async_engine = None
        _maintenance_async_session_factory = None


async def check_database_connection() -> None:
    """Verify connectivity and the non-local runtime/maintenance role boundary."""
    try:
        session_factory = get_async_db_session_factory()
        async with session_factory() as session:
            runtime_identity = (
                await session.execute(text("SELECT current_user, session_user"))
            ).one()

        if not settings.is_dev:
            maintenance_session_factory = get_maintenance_async_db_session_factory()
            async with maintenance_session_factory() as maintenance_session:
                maintenance_identity = (
                    await maintenance_session.execute(text("SELECT current_user, session_user"))
                ).one()
            runtime_current_user, runtime_session_user = tuple(runtime_identity)
            maintenance_current_user, maintenance_session_user = tuple(maintenance_identity)
            if (runtime_current_user, runtime_session_user) != (
                _RUNTIME_DATABASE_ROLE,
                _RUNTIME_DATABASE_ROLE,
            ):
                raise RuntimeError(
                    "DATABASE_URL must connect directly as the praxis_app runtime role"
                )
            if maintenance_current_user != maintenance_session_user:
                raise RuntimeError("DATABASE_MAINTENANCE_URL must connect without an assumed role")
            if maintenance_session_user == runtime_session_user:
                raise RuntimeError(
                    "Runtime and maintenance database connections must use distinct roles"
                )
    except Exception as exc:
        raise DatabaseError(
            "Database connection check failed",
            details={"error": str(exc), "error_type": type(exc).__name__},
        ) from exc
