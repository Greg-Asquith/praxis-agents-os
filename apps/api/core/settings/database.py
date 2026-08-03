# apps/api/core/settings/database.py

"""Database connection and pool settings."""

from urllib.parse import parse_qs, unquote, urlparse

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
        description="PostgreSQL runtime database URL",
    )
    DATABASE_MAINTENANCE_URL: str | None = Field(
        default=None,
        description=(
            "Owning PostgreSQL URL for migrations and deliberate cross-workspace work; "
            "defaults to DATABASE_URL in local development"
        ),
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

    @field_validator("DATABASE_URL", "DATABASE_MAINTENANCE_URL")
    @classmethod
    def validate_database_url(cls, v):
        """Validate the database URL is a PostgreSQL URL."""
        if v is None:
            return v
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

        if not self.DATABASE_MAINTENANCE_URL:
            raise ValueError(
                "DATABASE_MAINTENANCE_URL is required outside local/development environments"
            )
        if self.DATABASE_MAINTENANCE_URL == self.DATABASE_URL:
            raise ValueError(
                "DATABASE_MAINTENANCE_URL must differ from DATABASE_URL outside "
                "local/development environments"
            )

        runtime_username = _database_username(self.DATABASE_URL)
        maintenance_username = _database_username(self.DATABASE_MAINTENANCE_URL)
        if runtime_username != "praxis_app":
            raise ValueError(
                "DATABASE_URL must authenticate as the praxis_app role outside "
                "local/development environments"
            )
        if maintenance_username == runtime_username:
            raise ValueError(
                "DATABASE_MAINTENANCE_URL must authenticate as a role distinct from "
                "DATABASE_URL outside local/development environments"
            )

        for setting_name, value in (
            ("DATABASE_URL", self.DATABASE_URL),
            ("DATABASE_MAINTENANCE_URL", self.DATABASE_MAINTENANCE_URL),
        ):
            parseable = value.replace("postgresql+asyncpg://", "postgresql://", 1)
            parsed = urlparse(parseable)
            hostname = (parsed.hostname or "").lower()

            if hostname in _LOCALHOST_HOSTNAMES or "/cloudsql/" in value:
                continue

            query = parse_qs(parsed.query)
            has_enforced_ssl = any(
                allowed_value in query.get(param, [])
                for param, allowed_values in _ENFORCED_SSL_VALUES.items()
                for allowed_value in allowed_values
            )
            if not has_enforced_ssl:
                raise ValueError(
                    "Production database connections must use enforced SSL. Add "
                    f"sslmode=require (or stronger) to {setting_name}"
                )
        return self

    @property
    def maintenance_database_url(self) -> str:
        """Return the configured owning URL, with the local-only fallback."""
        return self.DATABASE_MAINTENANCE_URL or self.DATABASE_URL


def _database_username(value: str) -> str | None:
    parseable = value.replace("postgresql+asyncpg://", "postgresql://", 1)
    username = urlparse(parseable).username
    return unquote(username) if username is not None else None
