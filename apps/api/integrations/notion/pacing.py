# apps/api/integrations/notion/pacing.py

"""Best-effort per-process request pacing for Notion connections."""

import asyncio
from dataclasses import dataclass
from time import monotonic

_RATE_PER_SECOND = 3.0
_CAPACITY = 3.0
_MAX_KEYS = 256
_IDLE_TTL_SECONDS = 300.0


@dataclass
class _Bucket:
    tokens: float
    updated_at: float
    last_used_at: float


_buckets: dict[str, _Bucket] = {}
_lock = asyncio.Lock()


async def acquire(key: str) -> None:
    """Waits until one process-local request token is available for a connection."""
    normalized = key.strip()
    if not normalized:
        return
    while True:
        async with _lock:
            now = monotonic()
            _evict(now)
            bucket = _buckets.get(normalized)
            if bucket is None:
                _evict_for_capacity()
                bucket = _Bucket(tokens=_CAPACITY, updated_at=now, last_used_at=now)
                _buckets[normalized] = bucket
            elapsed = max(0.0, now - bucket.updated_at)
            bucket.tokens = min(_CAPACITY, bucket.tokens + elapsed * _RATE_PER_SECOND)
            bucket.updated_at = now
            bucket.last_used_at = now
            if bucket.tokens >= 1.0:
                bucket.tokens -= 1.0
                return
            wait_seconds = (1.0 - bucket.tokens) / _RATE_PER_SECOND
        await asyncio.sleep(wait_seconds)


def _evict(now: float) -> None:
    stale = [
        key for key, bucket in _buckets.items() if now - bucket.last_used_at >= _IDLE_TTL_SECONDS
    ]
    for key in stale:
        _buckets.pop(key, None)


def _evict_for_capacity() -> None:
    if len(_buckets) < _MAX_KEYS:
        return
    oldest = min(_buckets, key=lambda key: _buckets[key].last_used_at)
    _buckets.pop(oldest, None)


def _reset_for_tests() -> None:
    _buckets.clear()
