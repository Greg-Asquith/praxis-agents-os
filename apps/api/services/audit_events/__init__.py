# apps/api/services/audit_events/__init__.py

"""Audit event services.

Ordinary writes use :func:`safe_record_operation_audit_event`. Integration
mutations that promise durable evidence can instead require a committed pending
record before dispatch and a strict finalized record afterward.
"""

from services.audit_events.enums import (
    AuditAction,
    AuditActorType,
    AuditResourceType,
    AuditStatus,
)
from services.audit_events.get_event import get_audit_event_for_workspace
from services.audit_events.integration_events import record_integration_operation_audit_event
from services.audit_events.integration_operation_detail import (
    IntegrationOperationCounts,
    IntegrationOperationDetail,
    IntegrationOperationEffect,
    IntegrationOperationIntent,
    IntegrationOperationIntentGroup,
    IntegrationOperationOutcome,
    IntegrationOperationOutcomeGroup,
    IntegrationOperationTarget,
    PendingIntegrationOperationDetail,
    TerminalIntegrationOperationDetail,
    terminal_applied_operation_detail,
)
from services.audit_events.list_events import list_audit_events_for_workspace
from services.audit_events.operations import safe_record_operation_audit_event
from services.audit_events.queries import (
    get_audit_event,
    list_audit_events,
    list_audit_events_page,
    list_rolled_up_audit_events_page,
)
from services.audit_events.safe_record_independent_operation_audit_event import (
    safe_record_independent_operation_audit_event,
)
from services.audit_events.tool_events import record_tool_invocation_audit_event
from services.audit_events.user_events import record_user_audit_event
from services.audit_events.workspace_events import record_workspace_audit_event

__all__ = [
    "AuditAction",
    "AuditActorType",
    "AuditResourceType",
    "AuditStatus",
    "IntegrationOperationCounts",
    "IntegrationOperationDetail",
    "IntegrationOperationEffect",
    "IntegrationOperationIntent",
    "IntegrationOperationIntentGroup",
    "IntegrationOperationOutcome",
    "IntegrationOperationOutcomeGroup",
    "IntegrationOperationTarget",
    "PendingIntegrationOperationDetail",
    "TerminalIntegrationOperationDetail",
    "get_audit_event",
    "get_audit_event_for_workspace",
    "list_audit_events",
    "list_audit_events_for_workspace",
    "list_audit_events_page",
    "list_rolled_up_audit_events_page",
    "record_integration_operation_audit_event",
    "record_tool_invocation_audit_event",
    "record_user_audit_event",
    "record_workspace_audit_event",
    "safe_record_independent_operation_audit_event",
    "safe_record_operation_audit_event",
    "terminal_applied_operation_detail",
]
