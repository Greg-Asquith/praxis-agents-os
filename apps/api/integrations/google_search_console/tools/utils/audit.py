# apps/api/integrations/google_search_console/tools/utils/audit.py

"""Bounded provider-local audit evidence for Search Console reads."""

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
    entity_type: str,
) -> TerminalIntegrationOperationDetail:
    """Returns counts-only terminal audit evidence for a site read."""
    pending = PendingIntegrationOperationDetail(
        target=IntegrationOperationTarget(
            entity_type="google_search_console_site",
            external_id=entry.external_id,
            display_name=entry.display_name,
            integration_resource_id=str(entry.integration_resource_id),
        ),
        intent_groups=[
            IntegrationOperationIntentGroup(
                key=operation,
                action="read",
                entity_type=entity_type,
                items=[IntegrationOperationIntent(fields=fields)],
            )
        ],
    )
    return terminal_applied_operation_detail(pending)
