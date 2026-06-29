# apps/api/core/auth/sessions/base.py

"""Shared base state for session management."""

from datetime import timedelta

from core.settings import settings


class SessionManagerBase:
    """Base state for session manager mixins."""

    def __init__(self):
        self.default_session_duration = timedelta(days=settings.SESSION_DURATION_DAYS)
