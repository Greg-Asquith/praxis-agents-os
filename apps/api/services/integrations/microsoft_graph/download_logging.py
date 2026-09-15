# apps/api/services/integrations/microsoft_graph/download_logging.py

"""Exclude pre-authenticated download requests from HTTP client diagnostics."""

import logging
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar

_download_active: ContextVar[bool] = ContextVar("graph_download_active", default=False)


class _DownloadFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        return not _download_active.get()


_filter = _DownloadFilter()
for _name in (
    "httpx2",
    "httpcore2.connection",
    "httpcore2.http11",
    "httpcore2.http2",
    "httpcore2.proxy",
    "httpcore2.socks",
):
    logging.getLogger(_name).addFilter(_filter)


@contextmanager
def suppress_download_logging() -> Iterator[None]:
    """Suppresses HTTP diagnostics for this task without hiding concurrent requests."""
    token = _download_active.set(True)
    try:
        yield
    finally:
        _download_active.reset(token)
