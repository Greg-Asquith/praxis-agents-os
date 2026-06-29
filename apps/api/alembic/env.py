"""Alembic environment for async SQLAlchemy migrations."""

import asyncio
import os
from logging.config import fileConfig

from sqlalchemy import pool
from sqlalchemy.engine import Connection, make_url
from sqlalchemy.ext.asyncio import async_engine_from_config

import models  # noqa: F401
from alembic import context
from models.base import Base

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata

MANAGED_SCHEMAS = {None, "public", "app"}


def get_database_url() -> str:
    """Return the async PostgreSQL URL Alembic should use."""
    x_args = context.get_x_argument(as_dictionary=True)
    raw_url = (
        x_args.get("database_url")
        or os.environ.get("DATABASE_URL")
        or config.get_main_option("sqlalchemy.url")
    )
    if not raw_url:
        raise RuntimeError("DATABASE_URL or sqlalchemy.url must be configured for Alembic")

    url = make_url(raw_url)
    if url.drivername == "postgresql":
        url = url.set(drivername="postgresql+asyncpg")

    return url.render_as_string(hide_password=False)


def include_name(name: str | None, type_: str, parent_names: dict[str, str | None]) -> bool:
    """Limit autogenerate inspection to schemas managed by this app."""
    if type_ == "schema":
        return name in MANAGED_SCHEMAS

    schema_name = parent_names.get("schema_name")
    return schema_name in MANAGED_SCHEMAS


def run_migrations_offline() -> None:
    """Run migrations without opening a database connection."""
    url = get_database_url()
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        include_schemas=True,
        include_name=include_name,
        compare_type=True,
        compare_server_default=True,
    )

    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    """Configure Alembic against an active SQLAlchemy connection."""
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        include_schemas=True,
        include_name=include_name,
        compare_type=True,
        compare_server_default=True,
    )

    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    """Run migrations with SQLAlchemy's async engine."""
    configuration = config.get_section(config.config_ini_section) or {}
    configuration["sqlalchemy.url"] = get_database_url()

    connectable = async_engine_from_config(
        configuration,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)

    await connectable.dispose()


def run_migrations_online() -> None:
    """Run migrations with a live database connection."""
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
