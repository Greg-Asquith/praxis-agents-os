# apps/api/middleware/db_session.py

"""Request-scoped database session middleware."""

import logging
from collections.abc import Callable

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware

from core.database import configure_async_db_session, get_async_db_session_factory

logger = logging.getLogger(__name__)


class DBSessionMiddleware(BaseHTTPMiddleware):
    """Create a request-scoped database session and own its transaction boundary."""

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        session_factory = get_async_db_session_factory()
        async with session_factory() as session:
            request.state.db = session
            try:
                await configure_async_db_session(session)
                response = await call_next(request)
                if response.status_code < 400:
                    await session.commit()
                else:
                    await session.rollback()
                return response
            except Exception:
                try:
                    await session.rollback()
                except Exception:
                    logger.error("Failed to rollback database session", exc_info=True)
                raise
            finally:
                request.state.db = None
