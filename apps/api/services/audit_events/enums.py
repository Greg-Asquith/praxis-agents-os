# apps/api/services/audit_events/enums.py

"""Controlled vocabularies for audit events.

These StrEnums keep ``action``/``resource_type``/``actor_type``/``status`` values
consistent across writers so the log stays queryable. Members are plain strings,
so they persist and compare exactly like the literals they replace.
"""

from enum import StrEnum


class AuditAction(StrEnum):
    """What happened to the resource."""

    CREATE = "create"
    READ = "read"
    UPDATE = "update"
    DELETE = "delete"
    EXECUTE = "execute"
    ENABLE = "enable"
    DISABLE = "disable"


class AuditResourceType(StrEnum):
    """The kind of resource an event concerns."""

    WORKSPACE = "workspace"
    WORKSPACE_MEMBERSHIP = "workspace_membership"
    INVITATION = "invitation"
    NOTIFICATION = "notification"
    AGENT_SCHEDULE = "agent_schedule"
    AGENT_SCHEDULE_RUN = "agent_schedule_run"


class AuditActorType(StrEnum):
    """Who or what initiated the action."""

    USER = "user"
    SYSTEM = "system"
    AGENT = "agent"
    SERVICE = "service"


class AuditStatus(StrEnum):
    """Outcome of the action."""

    SUCCESS = "success"
    FAILURE = "failure"
    DENIED = "denied"
