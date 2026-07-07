# apps/api/core/observability.py

"""Observability helpers for HTTP metrics and agent runtime tracing."""

import logfire
from prometheus_client import Counter, Histogram, generate_latest
from pydantic_ai import Agent as PydanticAgent
from pydantic_ai.models.instrumented import InstrumentationSettings

from core.settings import settings

_agent_tracing_configured = False

# Prometheus metrics (kept intentionally small for serverless environments).
REQUEST_COUNT = Counter(
    "http_requests_total",
    "Total HTTP requests",
    ["method", "endpoint", "status"],
)
REQUEST_DURATION = Histogram(
    "http_request_duration_seconds", "HTTP request duration", ["method", "endpoint"]
)


def get_metrics() -> bytes:
    """Get current metrics in Prometheus format for the /metrics endpoint."""
    return generate_latest()


def setup_agent_tracing() -> None:
    """Instrument Pydantic AI agents when tracing is enabled."""
    global _agent_tracing_configured

    if not settings.AGENT_TRACING_ENABLED or _agent_tracing_configured:
        return

    logfire.configure(send_to_logfire="if-token-present")
    PydanticAgent.instrument_all(
        InstrumentationSettings(
            include_content=settings.AGENT_TRACING_INCLUDE_CONTENT,
            include_binary_content=False,
        )
    )
    _agent_tracing_configured = True


def track_request(method: str, endpoint: str, status_code: int, duration: float) -> None:
    """Track HTTP request metrics."""
    REQUEST_COUNT.labels(method=method, endpoint=endpoint, status=str(status_code)).inc()
    REQUEST_DURATION.labels(method=method, endpoint=endpoint).observe(duration)
