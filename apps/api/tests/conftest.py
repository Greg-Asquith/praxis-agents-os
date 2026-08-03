# apps/api/tests/conftest.py
"""Shared pytest fixtures for the API test suite."""

# ruff: noqa: E402

import os
from collections.abc import AsyncIterator
from contextvars import ContextVar
from pathlib import Path
from typing import Any
from uuid import UUID

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx2 import ASGITransport, AsyncClient
from pydantic_ai import ApprovalRequired, RunContext, models as pydantic_ai_models
from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import NullPool

from tests.support.database import make_async_test_database_url, require_test_database_url
from tests.support.settings import configure_test_environment

configure_test_environment()

from services.agents.runtime.context import RuntimeDeps
from services.agents.runtime.tools.contract import (
    TOOL_POLICY_APPROVAL,
    ToolFieldPresentation,
    ToolPresentation,
)
from services.agents.runtime.tools.registry import runtime_tool

pydantic_ai_models.ALLOW_MODEL_REQUESTS = False


class _RlsTestSession(Session):
    """Sync session used to seed one tenant while runtime RLS stays enabled."""


class _RlsTestAsyncSession(AsyncSession):
    sync_session_class = _RlsTestSession


_TEST_TENANT_INHERIT_KEY = "praxis_test_inherit_tenant"
_test_workspace_id: ContextVar[UUID | None] = ContextVar("test_workspace_id", default=None)
_test_user_id: ContextVar[UUID | None] = ContextVar("test_user_id", default=None)

_RLS_WORKSPACE_TABLES = frozenset(
    {
        "active_context_selections",
        "agent_memories",
        "agent_runs",
        "agent_schedule_runs",
        "agent_schedules",
        "agents",
        "artifact_revisions",
        "artifact_shares",
        "artifacts",
        "audit_events",
        "conversation_messages",
        "conversation_summaries",
        "conversation_todos",
        "conversations",
        "embedding_token_usage",
        "external_credentials",
        "file_references",
        "file_revisions",
        "file_uploads",
        "files",
        "integration_connections",
        "integration_context_groups",
        "kb_chunks",
        "kb_documents",
        "notifications",
        "scratch_entries",
        "skills",
        "workspace_tool_settings",
    }
)


@pytest.fixture(autouse=True)
def _reset_test_tenant_context():
    workspace_token = _test_workspace_id.set(None)
    user_token = _test_user_id.set(None)
    try:
        yield
    finally:
        _test_workspace_id.reset(workspace_token)
        _test_user_id.reset(user_token)


def _infer_test_tenant_context(
    session: Session,
    _flush_context: object,
    _instances: object,
) -> None:
    """Infer the single tenant used by ordinary test setup before its first flush."""
    from core.database import SESSION_USER_ID_KEY, SESSION_WORKSPACE_ID_KEY

    workspace_ids = {
        value
        for row in session.new
        if getattr(row, "__tablename__", None) in _RLS_WORKSPACE_TABLES
        for value in (
            getattr(row, "workspace_id", None),
            getattr(row, "owner_workspace_id", None),
        )
        if value is not None
    }
    if not workspace_ids:
        existing_workspace_id = session.info.get(SESSION_WORKSPACE_ID_KEY)
        workspace_ids = (
            {existing_workspace_id}
            if existing_workspace_id is not None
            else {
                row.id for row in session.new if getattr(row, "__tablename__", None) == "workspaces"
            }
        )
    user_ids = {
        value
        for row in session.new
        for value in (
            getattr(row, "owner_user_id", None),
            getattr(row, "recipient_user_id", None),
            getattr(row, "user_id", None),
        )
        if value is not None
    }
    if not user_ids:
        existing_user_id = session.info.get(SESSION_USER_ID_KEY)
        user_ids = (
            {existing_user_id}
            if existing_user_id is not None
            else {row.id for row in session.new if getattr(row, "__tablename__", None) == "users"}
        )
    if len(workspace_ids) == 1:
        workspace_id = workspace_ids.pop()
        session.info[SESSION_WORKSPACE_ID_KEY] = workspace_id
        _test_workspace_id.set(workspace_id)
    if len(user_ids) == 1:
        user_id = user_ids.pop()
        session.info[SESSION_USER_ID_KEY] = user_id
        _test_user_id.set(user_id)

    for row in session.new:
        if getattr(row, "__tablename__", None) != "external_credentials":
            continue
        if row.owner_user_id is not None or row.owner_workspace_id is not None:
            continue
        from services.integrations.manifest import PROVIDER_MANIFESTS

        manifest = PROVIDER_MANIFESTS.get(row.provider_key)
        if manifest is not None and manifest.owner_scope == "user":
            row.owner_user_id = session.info.get(SESSION_USER_ID_KEY)
        else:
            row.owner_workspace_id = session.info.get(SESSION_WORKSPACE_ID_KEY)

    connection = session.connection()
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


event.listen(_RlsTestSession, "before_flush", _infer_test_tenant_context)


def _restore_explicit_test_tenant_context(
    session: Session,
    _transaction: object,
    connection,
) -> None:
    """Carry fixture context only into test-owned sessions, never production factories."""
    if not session.info.get(_TEST_TENANT_INHERIT_KEY):
        return

    from core.database import SESSION_USER_ID_KEY, SESSION_WORKSPACE_ID_KEY

    for context_var, info_key, guc_name in (
        (_test_workspace_id, SESSION_WORKSPACE_ID_KEY, "app.current_workspace_id"),
        (_test_user_id, SESSION_USER_ID_KEY, "app.current_user_id"),
    ):
        if session.info.get(info_key) is not None:
            continue
        value = context_var.get()
        if value is not None:
            session.info[info_key] = value
            connection.execute(
                text("SELECT set_config(:name, :value, true)"),
                {"name": guc_name, "value": str(value)},
            )


event.listen(_RlsTestSession, "after_begin", _restore_explicit_test_tenant_context)


@runtime_tool(
    name="test_add_numbers",
    label="Test add numbers",
    description="Add two integers in tests.",
    timeout=5,
    max_retries=1,
    configurable=False,
    presentation=ToolPresentation(
        arg_fields=(
            ToolFieldPresentation(key="a", label="A", format="number", editable=True),
            ToolFieldPresentation(key="b", label="B", format="number", editable=True),
        )
    ),
)
def test_add_numbers(a: int, b: int) -> int:
    """Test-only approval-capable arithmetic fixture."""
    return a + b


@runtime_tool(
    name="test_conditional_integer",
    label="Test conditional integer",
    description="Echo an integer after conditional approval in tests.",
    takes_ctx=True,
    timeout=5,
    configurable=False,
    presentation=ToolPresentation(
        arg_fields=(
            ToolFieldPresentation(key="value", label="Value", format="number", editable=True),
        )
    ),
)
def test_conditional_integer(ctx: RunContext[RuntimeDeps], value: int) -> int:
    """Test-only conditional approval fixture."""
    if not ctx.tool_call_approved:
        raise ApprovalRequired(metadata={"reason": "integer_confirmation"})
    return value


@runtime_tool(
    name="test_runtime_context",
    label="Test runtime context",
    description="Read runtime identifiers in tests.",
    takes_ctx=True,
    timeout=5,
    provider="test",
    default_policy=TOOL_POLICY_APPROVAL,
    configurable=False,
)
async def test_runtime_context(ctx: RunContext[RuntimeDeps]) -> dict[str, str | None]:
    """Test-only context fixture."""
    deps = ctx.deps
    return {
        "workspace_id": str(deps.run.workspace_id),
        "conversation_id": str(deps.conversation.id),
        "agent_id": str(deps.agent.id),
        "run_id": str(deps.run.id),
        "agent_name": deps.agent.name,
        "agent_slug": deps.agent.slug,
    }


@pytest.fixture(scope="session")
def app() -> FastAPI:
    """Return the FastAPI app with test-safe environment defaults applied."""
    from main import app as fastapi_app

    return fastapi_app


@pytest.fixture(scope="session")
def openapi_schema(app: FastAPI) -> dict[str, Any]:
    """Return the generated OpenAPI schema for contract tests."""
    return app.openapi()


@pytest_asyncio.fixture
async def async_client(app: FastAPI) -> AsyncIterator[AsyncClient]:
    """Return an HTTPX client mounted directly against the ASGI app."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        yield client


@pytest.fixture(scope="session")
def test_database_url() -> str:
    """Return the configured PostgreSQL test database URL or skip cleanly."""
    return require_test_database_url()


@pytest.fixture(scope="session")
def migrated_test_database(test_database_url: str) -> str:
    """Apply migrations once to the configured PostgreSQL test database."""
    from alembic.config import Config

    from alembic import command

    os.environ["DATABASE_URL"] = test_database_url
    api_root = Path(__file__).resolve().parents[1]
    config = Config(str(api_root / "alembic.ini"))
    command.upgrade(config, "heads")
    return test_database_url


@pytest_asyncio.fixture
async def db_session_factory(
    migrated_test_database: str,
    monkeypatch: pytest.MonkeyPatch,
) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    """Bind app database sessions to a per-test rollback-only Postgres transaction."""
    from core import database as database_module
    from core.database import SESSION_MAINTENANCE_KEY

    engine = create_async_engine(
        make_async_test_database_url(migrated_test_database),
        poolclass=NullPool,
    )
    async with engine.connect() as connection:
        transaction = await connection.begin()
        session_factory = async_sessionmaker(
            bind=connection,
            class_=_RlsTestAsyncSession,
            expire_on_commit=False,
            join_transaction_mode="create_savepoint",
            info={_TEST_TENANT_INHERIT_KEY: True},
        )
        runtime_session_factory = async_sessionmaker(
            bind=connection,
            class_=_RlsTestAsyncSession,
            expire_on_commit=False,
            join_transaction_mode="create_savepoint",
        )
        monkeypatch.setattr(database_module, "_async_engine", engine)
        monkeypatch.setattr(database_module, "_async_session_factory", runtime_session_factory)
        maintenance_session_factory = async_sessionmaker(
            bind=connection,
            class_=AsyncSession,
            expire_on_commit=False,
            join_transaction_mode="create_savepoint",
            info={SESSION_MAINTENANCE_KEY: True},
        )
        monkeypatch.setattr(database_module, "_maintenance_async_engine", engine)
        monkeypatch.setattr(
            database_module,
            "_maintenance_async_session_factory",
            maintenance_session_factory,
        )

        try:
            yield session_factory
        finally:
            if transaction.is_active:
                await transaction.rollback()

    await engine.dispose()


@pytest_asyncio.fixture
async def committed_db_session_factory(
    migrated_test_database: str,
    monkeypatch: pytest.MonkeyPatch,
) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    """Bind app database sessions to independent committed Postgres connections.

    Use this only for durability/concurrency tests where separate workers must
    observe committed state and contend on real Postgres row locks.
    """
    from core import database as database_module
    from core.database import SESSION_MAINTENANCE_KEY

    engine = create_async_engine(
        make_async_test_database_url(migrated_test_database),
        poolclass=NullPool,
    )
    session_factory = async_sessionmaker(
        bind=engine,
        class_=_RlsTestAsyncSession,
        expire_on_commit=False,
        info={_TEST_TENANT_INHERIT_KEY: True},
    )
    runtime_session_factory = async_sessionmaker(
        bind=engine,
        class_=_RlsTestAsyncSession,
        expire_on_commit=False,
    )
    monkeypatch.setattr(database_module, "_async_engine", engine)
    monkeypatch.setattr(database_module, "_async_session_factory", runtime_session_factory)
    maintenance_session_factory = async_sessionmaker(
        bind=engine,
        class_=AsyncSession,
        expire_on_commit=False,
        info={SESSION_MAINTENANCE_KEY: True},
    )
    monkeypatch.setattr(database_module, "_maintenance_async_engine", engine)
    monkeypatch.setattr(
        database_module,
        "_maintenance_async_session_factory",
        maintenance_session_factory,
    )

    try:
        yield session_factory
    finally:
        await engine.dispose()


@pytest_asyncio.fixture
async def db_session(
    db_session_factory: async_sessionmaker[AsyncSession],
) -> AsyncIterator[AsyncSession]:
    """Return a database session isolated inside the current test transaction."""
    async with db_session_factory() as session:
        yield session


@pytest_asyncio.fixture
async def db_async_client(
    app: FastAPI,
    db_session_factory: async_sessionmaker[AsyncSession],
) -> AsyncIterator[AsyncClient]:
    """Return an ASGI client whose app database sessions use the test transaction."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        yield client
