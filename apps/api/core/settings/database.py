# apps/api/core/settings/database.py

"""Database connection and pool settings."""

from urllib.parse import parse_qs, urlparse

from pydantic import Field, field_validator, model_validator

_LOCALHOST_HOSTNAMES = frozenset({"localhost", "127.0.0.1", "::1"})
_ENFORCED_SSL_VALUES = {
    "sslmode": {"require", "verify-ca", "verify-full"},
    "ssl": {"require", "true"},
}


class DatabaseSettingsMixin:
    # Database Configuration
    DATABASE_URL: str = Field(
        default="postgresql+asyncpg://postgres:postgres@localhost:5432/postgres",
        description="PostgreSQL database URL",
    )
    IVFFLAT_PROBES: int = Field(
        default=10,
        ge=1,
        le=1000,
        description="Default number of inverted lists to probe for IVFFlat searches",
    )
    DB_POOL_SIZE: int = Field(
        default=5, ge=1, le=100, description="SQLAlchemy connection pool size per process"
    )
    DB_POOL_MAX_OVERFLOW: int = Field(
        default=10, ge=0, le=100, description="Max overflow connections beyond the pool size"
    )

    @field_validator("DATABASE_URL")
    @classmethod
    def validate_database_url(cls, v):
        """Validate the database URL is a PostgreSQL URL."""
        if not v.startswith(("postgresql://", "postgresql+asyncpg://")):
            raise ValueError("Database URL must be a valid PostgreSQL URL")
        return v

    @model_validator(mode="after")
    def validate_database_ssl(self):
        """Require enforced SSL outside dev environments.

        Runs as a model validator so ENVIRONMENT (defined on another mixin) is
        available. Local/development skip enforcement so Docker service
        hostnames (e.g. ``postgres``) and localhost work without TLS.
        """
        if getattr(self, "is_dev", False):
            return self

        v = self.DATABASE_URL
        parseable = v.replace("postgresql+asyncpg://", "postgresql://", 1)
        parsed = urlparse(parseable)
        hostname = (parsed.hostname or "").lower()

        if hostname in _LOCALHOST_HOSTNAMES or "/cloudsql/" in v:
            return self

        query = parse_qs(parsed.query)
        has_enforced_ssl = any(
            value in query.get(param, [])
            for param, values in _ENFORCED_SSL_VALUES.items()
            for value in values
        )
        if not has_enforced_ssl:
            raise ValueError(
                "Production database connections must use enforced SSL. Add sslmode=require "
                "(or stronger) to your DATABASE_URL"
            )
        return self
