# apps/api/core/settings/email.py

"""Provider-agnostic email settings."""

from pydantic import Field


class EmailSettingsMixin:
    EMAIL_ENABLED: bool = Field(default=True, description="Email enabled")
    EMAIL_FROM_NAME: str = Field(default="Praxis", description="Email from name")
    EMAIL_REPLY_TO: str = Field(default="noreply@praxis-agents.ai", description="Email reply to")
