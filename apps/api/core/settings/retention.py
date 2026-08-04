# apps/api/core/settings/retention.py

"""Audit and security event retention settings."""

from pydantic import Field, model_validator

PRODUCTION_EVENT_RETENTION_DAYS = 400


class EventRetentionSettingsMixin:
    AUDIT_EVENTS_RETENTION_DAYS: int = Field(
        default=PRODUCTION_EVENT_RETENTION_DAYS,
        gt=0,
        description="Days to retain append-only audit event rows.",
    )
    SECURITY_EVENTS_RETENTION_DAYS: int = Field(
        default=PRODUCTION_EVENT_RETENTION_DAYS,
        gt=0,
        description="Days to retain append-only security event rows.",
    )

    @model_validator(mode="after")
    def enforce_production_event_retention_floor(self):
        """Keep production evidence for at least the deployment-contract floor."""
        if getattr(self, "ENVIRONMENT", None) != "production":
            return self

        below_floor = [
            name
            for name in (
                "AUDIT_EVENTS_RETENTION_DAYS",
                "SECURITY_EVENTS_RETENTION_DAYS",
            )
            if getattr(self, name) < PRODUCTION_EVENT_RETENTION_DAYS
        ]
        if below_floor:
            raise ValueError(
                ", ".join(below_floor)
                + f" must be at least {PRODUCTION_EVENT_RETENTION_DAYS} in production"
            )
        return self
