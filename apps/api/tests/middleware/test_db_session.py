# apps/api/tests/middleware/test_db_session.py

"""Focused tests for request-scoped database session middleware."""

from fastapi import FastAPI, Request
from httpx2 import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from starlette.middleware.base import BaseHTTPMiddleware

from core import database as database_module
from core.settings import settings
from middleware.db_session import DBSessionMiddleware
from tests.support.database import make_async_test_database_url


async def test_request_session_leaves_the_pool_free_until_its_first_query(
    migrated_test_database: str,
    monkeypatch,
) -> None:
    engine_kwargs = database_module._engine_kwargs()
    engine_kwargs.pop("poolclass", None)
    engine = create_async_engine(
        make_async_test_database_url(migrated_test_database),
        **{**engine_kwargs, "pool_size": 1, "max_overflow": 0, "pool_timeout": 1},
    )
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    monkeypatch.setattr(database_module, "_async_session_factory", session_factory)

    async def independent_session(request: Request, call_next):
        # Rate limiting opens its own session inside the request session.
        async with session_factory() as db:
            await db.execute(text("SELECT 1"))
        return await call_next(request)

    app = FastAPI()
    app.add_middleware(BaseHTTPMiddleware, dispatch=independent_session)
    app.add_middleware(DBSessionMiddleware)

    @app.get("/probes")
    async def probes(request: Request) -> str:
        return (await request.state.db.execute(text("SHOW ivfflat.probes"))).scalar_one()

    try:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://testserver"
        ) as client:
            response = await client.get("/probes")
    finally:
        await engine.dispose()

    assert response.status_code == 200
    assert response.json() == str(settings.IVFFLAT_PROBES)
