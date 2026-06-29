# apps/api/core/settings/base.py

"""
Application configuration using Pydantic BaseSettings.

Loads configuration from environment variables with validation.
All secrets should be loaded from environment variables or secret management systems.
"""

from pydantic_settings import BaseSettings


class SettingsBase(BaseSettings):
    """Base class for composed application settings."""
