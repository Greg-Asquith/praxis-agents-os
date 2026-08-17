# apps/api/integrations/google_analytics/tools/utils/audit.py

"""Bounded provider-local audit evidence for Google Analytics reads."""

from services.audit_events import (
    IntegrationOperationIntent,
    IntegrationOperationIntentGroup,
    IntegrationOperationTarget,
    PendingIntegrationOperationDetail,
    TerminalIntegrationOperationDetail,
    terminal_applied_operation_detail,
)
from services.audit_events.integration_operation_detail import AuditDetailValue
from services.integrations.context.domain import ResolvedContextEntry


def read_operation_detail(
    entry: ResolvedContextEntry,
    *,
    operation: str,
    fields: dict[str, AuditDetailValue],
) -> TerminalIntegrationOperationDetail:
    pending = PendingIntegrationOperationDetail(
        target=IntegrationOperationTarget(
            entity_type="google_analytics_property",
            external_id=entry.external_id,
            display_name=entry.display_name,
            integration_resource_id=str(entry.integration_resource_id),
        ),
        intent_groups=[
            IntegrationOperationIntentGroup(
                key=operation,
                action="read",
                entity_type="google_analytics_report",
                items=[IntegrationOperationIntent(fields=fields)],
            )
        ],
    )
    return terminal_applied_operation_detail(pending)
