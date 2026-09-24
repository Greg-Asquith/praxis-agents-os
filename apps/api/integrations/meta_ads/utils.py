# apps/api/integrations/meta_ads/utils.py

"""Keep Meta proof-bearing requests out of HTTP diagnostics."""

import logging
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar

_request_active: ContextVar[bool] = ContextVar("meta_ads_request_active", default=False)


class _MetaRequestFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        return not _request_active.get()


_filter = _MetaRequestFilter()
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
def suppress_request_logging() -> Iterator[None]:
    """Suppresses proof-bearing diagnostics only in the calling task."""
    token = _request_active.set(True)
    try:
        yield
    finally:
        _request_active.reset(token)
