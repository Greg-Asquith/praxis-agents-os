# apps/api/core/settings/rate_limit.py

"""Rate limit and trusted proxy settings."""

from pydantic import Field


class RateLimitSettingsMixin:
    # Rate Limiting Configuration
    RATE_LIMIT_ENABLED: bool = Field(default=True, description="Enable rate limiting")
    RATE_LIMIT_REQUESTS_PER_MINUTE: int = Field(
        default=60, ge=1, le=1000, description="Maximum requests per minute per IP"
    )
    RATE_LIMIT_REQUESTS_PER_HOUR: int = Field(
        default=1000, ge=1, le=10000, description="Maximum requests per hour per IP"
    )
    RATE_LIMIT_LOGIN_ATTEMPTS_PER_HOUR: int = Field(
        default=5,
        ge=1,
        le=20,
        description="Maximum failed login attempts per hour per IP",
    )
    RATE_LIMIT_REGISTRATION_PER_DAY: int = Field(
        default=3,
        ge=1,
        le=10,
        description="Maximum registration attempts per day per IP",
    )
    RATE_LIMIT_PASSWORD_RESET_PER_DAY: int = Field(
        default=3,
        ge=1,
        le=10,
        description="Maximum password reset attempts per day per IP",
    )
    TRUSTED_PROXY_CIDRS: str = Field(
        default="127.0.0.1/32,::1/128",
        description="Comma-separated CIDR ranges for trusted reverse proxies/load balancers that are allowed to supply X-Forwarded-For/X-Real-IP",
    )
