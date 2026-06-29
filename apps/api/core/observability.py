# apps/api/core/observability.py

"""Prometheus metrics helpers for HTTP request telemetry."""

from prometheus_client import Counter, Histogram, generate_latest

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


def track_request(method: str, endpoint: str, status_code: int, duration: float) -> None:
    """Track HTTP request metrics."""
    REQUEST_COUNT.labels(method=method, endpoint=endpoint, status=str(status_code)).inc()
    REQUEST_DURATION.labels(method=method, endpoint=endpoint).observe(duration)
