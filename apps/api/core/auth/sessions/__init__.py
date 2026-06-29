# apps/api/core/auth/sessions/__init__.py

"""Public session-management exports."""

from core.auth.sessions.session_manager import session_manager

__all__ = ["session_manager"]
