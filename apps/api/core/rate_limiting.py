# apps/api/core/rate_limiting.py

"""
PostgreSQL-backed rate limiting system with Redis upgrade path.

Provides:
- IP-based rate limiting using database storage
- Configurable rate limits per endpoint
- Designed for easy migration to Redis
"""

import logging
import math
from datetime import UTC, datetime, timedelta
from functools import lru_cache
from ipaddress import ip_address, ip_network
from typing import Any

from fastapi import Request
from sqlalchemy import and_, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import get_async_db_session_factory
from core.exceptions.general import RateLimitError
from core.settings import settings
from models.rate_limiting import RateLimitAttempt

logger = logging.getLogger(__name__)


class RateLimitResult:
    """Result of a rate limit check."""

    def __init__(
        self,
        allowed: bool,
        attempts: int,
        limit: int | None,
        window_seconds: int,
        reset_time: datetime,
        retry_after: int | None = None,
    ):
        self.allowed = allowed
        self.attempts = attempts
        self.limit = limit
        self.window_seconds = window_seconds
        self.reset_time = reset_time
        self.retry_after = retry_after  # Seconds until next attempt allowed


class RateLimiter:
    """PostgreSQL-backed rate limiter with configurable limits."""

    def __init__(self):
        self.enabled = settings.RATE_LIMIT_ENABLED

        # Default rate limits from config
        self.default_limits = {
            "requests_per_minute": (settings.RATE_LIMIT_REQUESTS_PER_MINUTE, 60),
            "requests_per_hour": (settings.RATE_LIMIT_REQUESTS_PER_HOUR, 3600),
            "login_attempts": (settings.RATE_LIMIT_LOGIN_ATTEMPTS_PER_HOUR, 3600),
            "registration": (settings.RATE_LIMIT_REGISTRATION_PER_DAY, 86400),
            "password_reset": (settings.RATE_LIMIT_PASSWORD_RESET_PER_DAY, 86400),
        }

    async def check_rate_limit(
        self,
        ip: str,
        endpoint: str,
        limit_type: str = "requests_per_minute",
        custom_limit: int | None = None,
        custom_window: int | None = None,
        db: AsyncSession | None = None,
    ) -> RateLimitResult:
        """
        Check if request is within rate limits.

        Args:
            ip: Client IP address
            endpoint: API endpoint being accessed
            limit_type: Type of limit to apply
            custom_limit: Override default limit
            custom_window: Override default window (seconds)
            db: Database session (optional)
        """
        if not self.enabled:
            return RateLimitResult(
                allowed=True,
                attempts=0,
                limit=None,
                window_seconds=0,
                reset_time=datetime.now(UTC),
            )

        # Validate IP address
        try:
            ip_address(ip)
        except ValueError:
            # If IP is invalid, apply most restrictive limit
            logger.warning("Invalid IP address for rate limit: %s", ip)
            return RateLimitResult(
                allowed=False,
                attempts=999,
                limit=1,
                window_seconds=3600,
                reset_time=datetime.now(UTC) + timedelta(hours=1),
                retry_after=3600,
            )

        # Get limit configuration
        if custom_limit is not None and custom_window is not None:
            limit, window_seconds = custom_limit, custom_window
        elif limit_type in self.default_limits:
            limit, window_seconds = self.default_limits[limit_type]
        else:
            # Default to per-minute limit
            limit, window_seconds = self.default_limits["requests_per_minute"]

        # Use provided session or get new one
        if db is None:
            session_factory = get_async_db_session_factory()
            async with session_factory() as session:
                try:
                    result = await self._check_rate_limit_db(
                        session, ip, endpoint, limit_type, limit, window_seconds
                    )
                    await session.commit()
                    return result
                except Exception:
                    await session.rollback()
                    raise
        else:
            return await self._check_rate_limit_db(
                db, ip, endpoint, limit_type, limit, window_seconds
            )

    async def _check_rate_limit_db(
        self,
        db: AsyncSession,
        ip: str,
        endpoint: str,
        limit_type: str,
        limit: int,
        window_seconds: int,
    ) -> RateLimitResult:
        """Internal method to check rate limits using database."""
        now = datetime.now(UTC)
        window_start = self._window_start(now, window_seconds)
        reset_time = window_start + timedelta(seconds=window_seconds)

        insert_stmt = insert(RateLimitAttempt).values(
            ip_address=ip,
            endpoint=endpoint,
            limit_type=limit_type,
            window_seconds=window_seconds,
            attempts=1,
            window_start=window_start,
            updated_at=now,
        )
        stmt = insert_stmt.on_conflict_do_update(
            index_elements=[
                RateLimitAttempt.ip_address,
                RateLimitAttempt.endpoint,
                RateLimitAttempt.limit_type,
                RateLimitAttempt.window_seconds,
                RateLimitAttempt.window_start,
            ],
            set_={
                "attempts": RateLimitAttempt.attempts + 1,
                "updated_at": now,
            },
        ).returning(RateLimitAttempt.attempts)

        result = await db.execute(stmt)
        attempts = result.scalar_one()

        allowed = attempts <= limit
        retry_after = None if allowed else self._seconds_until(reset_time, now)

        return RateLimitResult(
            allowed=allowed,
            attempts=attempts,
            limit=limit,
            window_seconds=window_seconds,
            reset_time=reset_time,
            retry_after=retry_after,
        )

    async def get_rate_limit_status(
        self,
        ip: str,
        endpoint: str,
        limit_type: str = "requests_per_minute",
        db: AsyncSession | None = None,
    ) -> dict[str, Any]:
        """Get current rate limit status without incrementing counter."""
        if not self.enabled:
            return {
                "attempts": 0,
                "limit": None,
                "remaining": None,
                "reset_time": None,
                "enabled": False,
            }

        # Get limit configuration
        if limit_type in self.default_limits:
            limit, window_seconds = self.default_limits[limit_type]
        else:
            limit, window_seconds = self.default_limits["requests_per_minute"]

        if db is None:
            session_factory = get_async_db_session_factory()
            async with session_factory() as session:
                return await self._get_status_db(
                    session, ip, endpoint, limit_type, limit, window_seconds
                )
        else:
            return await self._get_status_db(db, ip, endpoint, limit_type, limit, window_seconds)

    async def _get_status_db(
        self,
        db: AsyncSession,
        ip: str,
        endpoint: str,
        limit_type: str,
        limit: int,
        window_seconds: int,
    ) -> dict[str, Any]:
        """Get rate limit status from database."""
        now = datetime.now(UTC)
        window_start = self._window_start(now, window_seconds)
        reset_time = window_start + timedelta(seconds=window_seconds)

        stmt = select(RateLimitAttempt.attempts).where(
            and_(
                RateLimitAttempt.ip_address == ip,
                RateLimitAttempt.endpoint == endpoint,
                RateLimitAttempt.limit_type == limit_type,
                RateLimitAttempt.window_seconds == window_seconds,
                RateLimitAttempt.window_start == window_start,
            )
        )

        result = await db.execute(stmt)
        total_attempts = result.scalar_one_or_none() or 0
        remaining = max(0, limit - total_attempts)

        return {
            "attempts": total_attempts,
            "limit": limit,
            "remaining": remaining,
            "reset_time": reset_time.isoformat(),
            "enabled": True,
        }

    @staticmethod
    def _window_start(now: datetime, window_seconds: int) -> datetime:
        bucket_epoch = int(now.timestamp()) // window_seconds * window_seconds
        return datetime.fromtimestamp(bucket_epoch, UTC)

    @staticmethod
    def _seconds_until(reset_time: datetime, now: datetime) -> int:
        return max(1, math.ceil((reset_time - now).total_seconds()))


# Global rate limiter instance
rate_limiter = RateLimiter()


@lru_cache(maxsize=32)
def _parse_trusted_proxy_networks(cidr_config: str) -> tuple:
    """Parse trusted proxy CIDR config into networks."""
    networks = []
    for cidr in (cidr.strip() for cidr in cidr_config.split(",") if cidr.strip()):
        try:
            networks.append(ip_network(cidr, strict=False))
        except ValueError:
            logger.warning("Ignoring invalid TRUSTED_PROXY_CIDRS entry: %s", cidr)
    return tuple(networks)


def _normalize_ip_candidate(value: str | None) -> str | None:
    """Normalize a potential IP value to canonical string form."""
    if value is None:
        return None

    candidate = value.strip().strip('"')
    if not candidate or candidate.lower() == "unknown":
        return None

    # Accept RFC7239-like values when passed through by upstream components.
    if candidate.lower().startswith("for="):
        candidate = candidate[4:].strip().strip('"')

    # Handle bracketed IPv6 with optional port, e.g. [2001:db8::1]:443.
    if candidate.startswith("[") and "]" in candidate:
        candidate = candidate[1 : candidate.index("]")]

    # Handle IPv4 host:port values.
    if candidate.count(":") == 1 and "." in candidate:
        host, _, port = candidate.partition(":")
        if port.isdigit():
            candidate = host

    try:
        return str(ip_address(candidate))
    except ValueError:
        return None


def _is_trusted_proxy_ip(client_ip: str) -> bool:
    """Check whether an IP belongs to trusted proxy CIDRs."""
    trusted_networks = _parse_trusted_proxy_networks(settings.TRUSTED_PROXY_CIDRS)
    if not trusted_networks:
        return False

    try:
        client_addr = ip_address(client_ip)
    except ValueError:
        return False

    return any(client_addr in network for network in trusted_networks)


def _extract_forwarded_chain(forwarded_for: str | None) -> list[str]:
    """Extract valid IPs from X-Forwarded-For preserving order."""
    if not forwarded_for:
        return []

    ips: list[str] = []
    for raw in forwarded_for.split(","):
        normalized = _normalize_ip_candidate(raw)
        if normalized:
            ips.append(normalized)
    return ips


def _resolve_ip_from_forwarded_chain(forwarded_chain: list[str], socket_ip: str) -> str | None:
    """Resolve client IP from forwarded chain using trusted-proxy boundaries."""
    if not forwarded_chain:
        return None

    full_chain = [*forwarded_chain, socket_ip]

    # Walk right-to-left and return the first non-trusted hop.
    for hop_ip in reversed(full_chain):
        if not _is_trusted_proxy_ip(hop_ip):
            return hop_ip

    # If all hops are trusted, keep the original left-most client candidate.
    return forwarded_chain[0]


def get_client_ip(request) -> str:
    """Extract client IP with trusted-proxy validation for forwarding headers."""
    socket_host = None
    if hasattr(request, "client") and request.client and request.client.host:
        socket_host = request.client.host.strip()

    if not socket_host:
        return "unknown"

    socket_ip = _normalize_ip_candidate(socket_host)
    if socket_ip is None:
        # Preserve existing behaviour for non-IP client hosts (e.g. some test clients).
        return socket_host

    # Never trust forwarding headers unless the immediate peer is a trusted proxy.
    if not _is_trusted_proxy_ip(socket_ip):
        return socket_ip

    forwarded_chain = _extract_forwarded_chain(request.headers.get("X-Forwarded-For"))
    resolved_forwarded_ip = _resolve_ip_from_forwarded_chain(forwarded_chain, socket_ip)
    if resolved_forwarded_ip:
        return resolved_forwarded_ip

    real_ip = _normalize_ip_candidate(request.headers.get("X-Real-IP"))
    if real_ip:
        return real_ip

    # Trusted proxy source but no valid forwarding header.
    return socket_ip


# Rate Limiting Decorators and Dependencies


def _build_rate_limit_error(result: "RateLimitResult") -> RateLimitError:
    """Build the RFC-7807 RateLimitError (body + headers) for a blocked result."""
    remaining = max(0, result.limit - result.attempts)
    return RateLimitError(
        message=f"Rate limit exceeded. Try again in {result.retry_after} seconds.",
        retry_after=result.retry_after,
        limit=result.limit,
        details={
            "rate_limit": {
                "limit": result.limit,
                "remaining": remaining,
                "reset": result.reset_time.isoformat(),
                "retry_after": result.retry_after,
            }
        },
        headers={
            "X-RateLimit-Limit": str(result.limit),
            "X-RateLimit-Remaining": str(remaining),
            "X-RateLimit-Reset": str(int(result.reset_time.timestamp())),
            "Retry-After": str(result.retry_after) if result.retry_after else None,
        },
    )


def require_rate_limit(
    limit_type: str = "requests_per_minute",
    custom_limit: int | None = None,
    custom_window: int | None = None,
):
    """
    FastAPI dependency for rate limiting.

    Usage:
        @app.get("/api/v1/some-endpoint")
        async def endpoint(request: Request, _: None = Depends(require_rate_limit("login_attempts"))):
            pass
    """

    async def dependency(request: Request):
        client_ip = get_client_ip(request)
        endpoint = request.url.path

        result = await rate_limiter.check_rate_limit(
            ip=client_ip,
            endpoint=endpoint,
            limit_type=limit_type,
            custom_limit=custom_limit,
            custom_window=custom_window,
        )

        if not result.allowed:
            raise _build_rate_limit_error(result)

        return  # Dependency satisfied

    return dependency
