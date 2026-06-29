# apps/api/core/auth/sessions/session_manager.py

"""
Session manager for handling user session operations.

Provides:
- Session creation and validation
- Session refresh and cleanup
- Device management for multiple sessions
- Secure cookie handling
"""

from core.auth.sessions.analytics import SessionAnalyticsMixin
from core.auth.sessions.base import SessionManagerBase
from core.auth.sessions.cleanup import SessionCleanupMixin
from core.auth.sessions.cookies import SessionCookieMixin
from core.auth.sessions.lifecycle import SessionLifecycleMixin
from core.auth.sessions.partial_sessions import PartialSessionMixin


class SessionManager(
    SessionLifecycleMixin,
    PartialSessionMixin,
    SessionCleanupMixin,
    SessionCookieMixin,
    SessionAnalyticsMixin,
    SessionManagerBase,
):
    """Manages user sessions with database persistence and secure token handling"""


# Global instance
session_manager = SessionManager()
