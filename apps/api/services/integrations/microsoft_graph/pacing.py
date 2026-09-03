# apps/api/services/integrations/microsoft_graph/pacing.py

"""Best-effort per-process pacing for Microsoft Graph connections.

When all keyed buckets are active, unseen connections share one overflow
bucket so the keyed collection remains bounded without rejecting reads.
"""

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from time import monotonic

from core.settings import settings

_CAPACITY = 4.0
_MAX_KEYS = 256
_IDLE_TTL_SECONDS = 300.0


@dataclass
class _Bucket:
    tokens: float
    updated_at: float
    last_used_at: float
    semaphore: asyncio.Semaphore
    active: int = 0


_buckets: dict[str, _Bucket] = {}
_overflow_bucket: _Bucket | None = None
_lock = asyncio.Lock()


@asynccontextmanager
async def paced_request(key: str) -> AsyncIterator[None]:
    """Enforce the process-local rate and concurrency bounds for one request."""
    normalized = key.strip()
    if not normalized:
        yield
        return
    async with _lock:
        now = monotonic()
        _evict(now)
        bucket = _buckets.get(normalized)
        if bucket is None:
            _evict_for_capacity()
            if len(_buckets) < _MAX_KEYS:
                bucket = _new_bucket(now)
                _buckets[normalized] = bucket
            else:
                bucket = _shared_overflow_bucket(now)
        bucket.active += 1
        bucket.last_used_at = now
    acquired = False
    try:
        await bucket.semaphore.acquire()
        acquired = True
        await _acquire_token(bucket)
        yield
    finally:
        if acquired:
            bucket.semaphore.release()
        async with _lock:
            bucket.active -= 1
            bucket.last_used_at = monotonic()


async def _acquire_token(bucket: _Bucket) -> None:
    while True:
        async with _lock:
            now = monotonic()
            rate = settings.MICROSOFT_GRAPH_REQUESTS_PER_SECOND
            elapsed = max(0.0, now - bucket.updated_at)
            bucket.tokens = min(_CAPACITY, bucket.tokens + elapsed * rate)
            bucket.updated_at = now
            bucket.last_used_at = now
            if bucket.tokens >= 1.0:
                bucket.tokens -= 1.0
                return
            wait_seconds = (1.0 - bucket.tokens) / rate
        await asyncio.sleep(wait_seconds)


def _evict(now: float) -> None:
    stale = [
        key
        for key, bucket in _buckets.items()
        if bucket.active == 0 and now - bucket.last_used_at >= _IDLE_TTL_SECONDS
    ]
    for key in stale:
        _buckets.pop(key, None)


def _evict_for_capacity() -> None:
    if len(_buckets) < _MAX_KEYS:
        return
    inactive = [key for key, bucket in _buckets.items() if bucket.active == 0]
    if not inactive:
        return
    oldest = min(inactive, key=lambda key: _buckets[key].last_used_at)
    _buckets.pop(oldest, None)


def _new_bucket(now: float) -> _Bucket:
    return _Bucket(
        tokens=_CAPACITY,
        updated_at=now,
        last_used_at=now,
        semaphore=asyncio.Semaphore(int(_CAPACITY)),
    )


def _shared_overflow_bucket(now: float) -> _Bucket:
    global _overflow_bucket
    if _overflow_bucket is None:
        _overflow_bucket = _new_bucket(now)
    return _overflow_bucket


def _reset_for_tests() -> None:
    global _overflow_bucket
    _buckets.clear()
    _overflow_bucket = None
