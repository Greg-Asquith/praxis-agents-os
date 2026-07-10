# apps/api/core/logging.py

"""Application logging setup with trace-aware structured formatting."""

import json
import logging
import sys
import uuid
from contextvars import ContextVar
from datetime import UTC, datetime

from core.settings import settings

# Trace ID propagates across async boundaries via a context variable.
_trace_id_var: ContextVar[str | None] = ContextVar("trace_id", default=None)

_EXCLUDED_LOG_RECORD_FIELDS = {
    "name",
    "msg",
    "args",
    "levelname",
    "levelno",
    "pathname",
    "filename",
    "module",
    "exc_info",
    "exc_text",
    "stack_info",
    "lineno",
    "funcName",
    "created",
    "msecs",
    "relativeCreated",
    "thread",
    "threadName",
    "processName",
    "process",
    "message",
    "taskName",
}

_DEV_EXCLUDED_LOG_RECORD_FIELDS = _EXCLUDED_LOG_RECORD_FIELDS | {"asctime"}


def _extract_extra_fields(
    record: logging.LogRecord, *, excluded_fields: set[str], skip_private: bool = False
) -> dict[str, object]:
    """Return custom fields attached via `extra=` on the log record."""
    extras: dict[str, object] = {}
    for key, value in record.__dict__.items():
        if key in excluded_fields:
            continue
        if skip_private and key.startswith("_"):
            continue
        extras[key] = value
    return extras


def get_trace_id() -> str | None:
    """Get the current trace ID from context."""
    return _trace_id_var.get()


def set_trace_id(trace_id: str | None) -> None:
    """Set the trace ID in context."""
    _trace_id_var.set(trace_id)


def generate_trace_id() -> str:
    """Generate a new trace ID and set it in context."""
    trace_id = str(uuid.uuid4())
    set_trace_id(trace_id)
    return trace_id


def clear_trace_id() -> None:
    """Clear the trace ID from context."""
    _trace_id_var.set(None)


class StructuredFormatter(logging.Formatter):
    """Format log records as JSON for structured logging."""

    def format(self, record: logging.LogRecord) -> str:
        """Return a structured JSON log line."""
        log_data = {
            "timestamp": datetime.fromtimestamp(record.created, UTC)
            .isoformat()
            .replace("+00:00", "Z"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "module": record.module,
            "function": record.funcName,
            "line": record.lineno,
        }

        # Add trace_id from context if available
        trace_id = get_trace_id()
        if trace_id:
            log_data["trace_id"] = trace_id

        # Add exception information if present
        if record.exc_info:
            log_data["exception"] = {
                "type": record.exc_info[0].__name__ if record.exc_info[0] else None,
                "message": str(record.exc_info[1]) if record.exc_info[1] else None,
                "traceback": self.formatException(record.exc_info),
            }

        # Include any custom fields passed via `extra=...`.
        extra_fields = _extract_extra_fields(record, excluded_fields=_EXCLUDED_LOG_RECORD_FIELDS)
        if extra_fields:
            log_data["extra"] = extra_fields

        return json.dumps(log_data, default=str)


class DevelopmentFormatter(logging.Formatter):
    """Format log records for human-readable local development."""

    def __init__(self) -> None:
        super().__init__(
            fmt="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )

    def format(self, record: logging.LogRecord) -> str:
        """Return a compact, readable log line."""
        formatted = super().format(record)

        # Add trace_id from context if available
        trace_id = get_trace_id()
        if trace_id:
            # Use short trace ID for readability in development
            formatted = f"{formatted} | trace={trace_id[:8]}"

        extra_fields = _extract_extra_fields(
            record,
            excluded_fields=_DEV_EXCLUDED_LOG_RECORD_FIELDS,
            skip_private=True,
        )
        if extra_fields:
            extra_str = " | ".join(f"{k}={v}" for k, v in extra_fields.items())
            formatted += f" | {extra_str}"

        return formatted


def setup_logging() -> None:
    """Configure root logging and common third-party logger levels."""
    formatter: logging.Formatter = (
        DevelopmentFormatter() if settings.is_dev else StructuredFormatter()
    )

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(formatter)

    # Root logger owns the single stream handler; children inherit it.
    root_logger = logging.getLogger()
    root_logger.handlers.clear()
    root_logger.addHandler(handler)
    root_logger.setLevel(getattr(logging, settings.LOG_LEVEL))

    is_development = settings.is_dev
    logger_configs = {
        # Application loggers
        "app": logging.INFO,
        "core.exception_handlers": logging.INFO,
        "core.exceptions": logging.DEBUG if is_development else logging.INFO,
        # FastAPI and Uvicorn
        "uvicorn": logging.INFO if is_development else logging.WARNING,
        "uvicorn.access": logging.INFO if is_development else logging.WARNING,
        "uvicorn.error": logging.WARNING,
        # SQLAlchemy
        "sqlalchemy.engine": logging.INFO if settings.SQL_DEBUG else logging.WARNING,
        "sqlalchemy.pool": logging.WARNING,
        "sqlalchemy.dialects": logging.WARNING,
        # HTTP libraries used directly and by transitive dependencies.
        "httpx": logging.WARNING,
        "httpx2": logging.WARNING,
        "urllib3": logging.WARNING,
        # OAuth libraries
        "authlib": logging.INFO if is_development else logging.WARNING,
        # Azure SDK
        "azure.core.pipeline.policies.http_logging_policy": logging.WARNING,
        "azure.identity": logging.WARNING,
        # Silence noisy loggers
        "asyncio": logging.WARNING,
        "multipart": logging.WARNING,
    }

    for logger_name, level in logger_configs.items():
        logger = logging.getLogger(logger_name)
        logger.setLevel(level)

    app_logger = logging.getLogger("app")
    app_logger.info(
        "Logging configured successfully",
        extra={
            "log_level": settings.LOG_LEVEL.lower(),
            "environment": settings.ENVIRONMENT.lower(),
            "structured_logging": not is_development,
        },
    )
