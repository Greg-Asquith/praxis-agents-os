# apps/api/services/security/enums.py

"""Controlled vocabulary for security events.

This StrEnum keeps ``event_type`` values consistent across writers so the log
stays queryable. Members are plain strings, so they persist and compare exactly
like the literals they replace.
"""

from enum import StrEnum


class SecurityEventType(StrEnum):
    """The kind of security-relevant activity recorded."""

    AUTH_LOGIN_SUCCEEDED = "auth_login_succeeded"
    AUTH_LOGIN_FAILED = "auth_login_failed"
    AUTH_ACCOUNT_LOCKED = "auth_account_locked"
    AUTH_LOGOUT_SUCCEEDED = "auth_logout_succeeded"
    AUTH_OAUTH_STARTED = "auth_oauth_started"
    AUTH_OAUTH_SUCCEEDED = "auth_oauth_succeeded"
    AUTH_OAUTH_FAILED = "auth_oauth_failed"
    AUTH_PASSWORD_CHANGED = "auth_password_changed"
    AUTH_REGISTER_SUCCEEDED = "auth_register_succeeded"
    AUTH_REGISTER_FAILED = "auth_register_failed"
    AUTH_SESSION_REFRESHED = "auth_session_refreshed"
    AUTH_SESSION_REVOKED = "auth_session_revoked"
    AUTH_TOTP_CHALLENGE_CREATED = "auth_totp_challenge_created"
    AUTH_TOTP_DISABLED = "auth_totp_disabled"
    AUTH_TOTP_ENABLED = "auth_totp_enabled"
    AUTH_TOTP_FAILED = "auth_totp_failed"
    AUTH_TOTP_VERIFIED = "auth_totp_verified"
    RATE_LIMIT_EXCEEDED = "rate_limit_exceeded"
    CSRF_VALIDATION_FAILED = "csrf_validation_failed"
    WORKSPACE_MEMBERSHIP_CREATED = "workspace_membership_created"
    WORKSPACE_MEMBERSHIP_UPDATED = "workspace_membership_updated"
    WORKSPACE_MEMBERSHIP_DELETED = "workspace_membership_deleted"
    WORKSPACE_INVITATION_CREATED = "workspace_invitation_created"
    WORKSPACE_INVITATION_UPDATED = "workspace_invitation_updated"
    WORKSPACE_INVITATION_DELETED = "workspace_invitation_deleted"
    WORKSPACE_INVITATION_ACCEPTED = "workspace_invitation_accepted"
    WORKSPACE_INVITATION_FAILED = "workspace_invitation_failed"
