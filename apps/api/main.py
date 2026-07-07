# apps/api/main.py

"""
Main application entry point.

Initializes the FastAPI application with all routes and middleware.
"""

import logging
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from core.database import check_database_connection, close_db_connections
from core.exceptions.exception_handlers import register_exception_handlers
from core.logging import setup_logging
from core.observability import setup_agent_tracing
from core.settings import settings
from middleware import (
    AuditContextMiddleware,
    BodySizeLimitMiddleware,
    CSRFMiddleware,
    DBSessionMiddleware,
    RateLimitMiddleware,
    RequestIDMiddleware,
    RequestLoggingMiddleware,
    SecurityHeadersMiddleware,
)
from routes import api_router
from services.agents.runtime import run_task_registry, sweep_abandoned_agent_runs_on_startup
from services.agents.runtime.events import STREAM_VERSION_HEADER
from services.notifications.registration import register_notification_action_handlers

# Initialize logging as early as possible so all subsequent loggers/middleware use it
setup_logging()
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifespan context manager for startup and shutdown events"""
    # Startup
    logger.info("Starting FastAPI application...")
    setup_agent_tracing()
    register_notification_action_handlers()
    logger.info("Notification action handlers registered")

    # Verify database connection
    try:
        await check_database_connection()
        logger.info("Database connection verified and healthy")
    except Exception:
        logger.error("Database connection failed", exc_info=True)
        raise

    await sweep_abandoned_agent_runs_on_startup()

    yield

    # Shutdown
    logger.info("Shutting down FastAPI application...")
    await run_task_registry.drain(max_wait_seconds=settings.AGENT_RUN_SHUTDOWN_DRAIN_SECONDS)
    await close_db_connections()


app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
    lifespan=lifespan,
)

# Register middleware. Starlette uses LIFO order: the LAST call to
# add_middleware produces the OUTERMOST layer (first to run on the request
# path). The intended request-entry order is:
#   CORS → RequestID → SecurityHeaders → CSRF → BodySizeLimit
#   → RequestLogging → DBSession → RateLimit → AuditContext → route
# RequestID is outermost (below CORS) so error responses short-circuited by
# CSRF (403) or BodySizeLimit (413) still carry X-Request-ID for correlation.
app.add_middleware(AuditContextMiddleware)
app.add_middleware(RateLimitMiddleware)
app.add_middleware(DBSessionMiddleware)
app.add_middleware(RequestLoggingMiddleware)
app.add_middleware(BodySizeLimitMiddleware)
app.add_middleware(CSRFMiddleware)
app.add_middleware(SecurityHeadersMiddleware)
app.add_middleware(RequestIDMiddleware)

# Register CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS"],
    allow_headers=[
        "Content-Type",
        "Authorization",
        "X-Workspace",
        "X-CSRF-Token",
        "X-Praxis-App-Frame-Token",
        "X-Request-ID",
        "Accept",
        "Origin",
        "User-Agent",
    ],
    expose_headers=[STREAM_VERSION_HEADER],
)

# Register custom exception handlers including overrides for FastAPI and Starlette built-in HTTPException
register_exception_handlers(app)

# Register API routes.
app.include_router(api_router)

if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=settings.DEBUG, log_level="info")
