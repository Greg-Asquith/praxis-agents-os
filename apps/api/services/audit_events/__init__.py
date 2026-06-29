# apps/api/services/audit_events/__init__.py

"""Audit event services.

Writes go through :func:`safe_record_operation_audit_event` so a failed audit
write never rolls back the operation being audited.
"""

from services.audit_events.enums import (
    AuditAction,
    AuditActorType,
    AuditResourceType,
    AuditStatus,
)
from services.audit_events.operations import safe_record_operation_audit_event
from services.audit_events.queries import (
    count_audit_events,
    get_audit_event,
    list_audit_events,
)
from services.audit_events.user_events import record_user_audit_event

__all__ = [
    "AuditAction",
    "AuditActorType",
    "AuditResourceType",
    "AuditStatus",
    "count_audit_events",
    "get_audit_event",
    "list_audit_events",
    "record_user_audit_event",
    "safe_record_operation_audit_event",
]
