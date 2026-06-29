# apps/api/core/settings/app.py

"""Application metadata, feature gate, environment, and logging settings."""

from typing import Literal

from pydantic import Field, model_validator


class AppSettingsMixin:
    # App Configuration
    APP_NAME: str = Field(default="Praxis Agents OS", description="Application name")
    APP_VERSION: str = Field(default="1.0.0", description="Application version")

    # Key Feature Gates
    ALLOW_SIGNUP: bool = Field(default=True, description="Allow new user registrations")
    ALLOW_WORKSPACE_CREATION: bool = Field(default=True, description="Allow new workspace creation")

    # Environment Configuration
    ENVIRONMENT: Literal["local", "development", "staging", "production"] = Field(
        default="development", description="Application environment"
    )
    DEBUG: bool = Field(default=False, description="Enable debug mode")
    SQL_DEBUG: bool = Field(default=False, description="Enable SQL debug mode")

    # Logging Configuration
    LOG_LEVEL: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = Field(
        default="INFO", description="Logging level"
    )

    @model_validator(mode="after")
    def reject_sql_debug_in_production(self):
        """SQL_DEBUG echoes full SQL (including user data); never allow it in prod."""
        if self.SQL_DEBUG and self.ENVIRONMENT == "production":
            raise ValueError("SQL_DEBUG must be disabled when ENVIRONMENT=production")
        return self
