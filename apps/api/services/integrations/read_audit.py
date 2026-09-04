# apps/api/services/integrations/read_audit.py

"""Provider-neutral terminal audit evidence for integration reads."""

from typing import Literal

from services.audit_events import (
    AuditStatus,
    IntegrationOperationCounts,
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
from services.audit_events.integration_operation_detail import AuditDetailValue
from services.integrations.context.domain import ResolvedContextEntry

type ReadAuditStatus = Literal[AuditStatus.SUCCESS, AuditStatus.PARTIAL]


def read_operation_detail(
    entry: ResolvedContextEntry,
    *,
    operation: str,
    fields: dict[str, AuditDetailValue],
    target_entity_type: str,
    entity_type: str,
    status: ReadAuditStatus = AuditStatus.SUCCESS,
) -> TerminalIntegrationOperationDetail:
    """Return counts-only terminal evidence for one aggregate provider read."""
    pending = PendingIntegrationOperationDetail(
        target=IntegrationOperationTarget(
            entity_type=target_entity_type,
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
    if status == AuditStatus.SUCCESS:
        return terminal_applied_operation_detail(pending)
    if status != AuditStatus.PARTIAL:
        raise ValueError("Aggregate read evidence supports success or partial outcomes")

    group = pending.intent_groups[0]
    return TerminalIntegrationOperationDetail(
        target=pending.target,
        intent_groups=pending.intent_groups,
        outcome_groups=[
            IntegrationOperationOutcomeGroup(
                key=group.key,
                outcomes=[
                    IntegrationOperationOutcome(
                        intent_index=0,
                        status="failed",
                        effects=[
                            IntegrationOperationEffect(status="applied"),
                            IntegrationOperationEffect(
                                status="failed",
                                error_code="PARTIAL_PROVIDER_FAILURE",
                            ),
                        ],
                    )
                ],
            )
        ],
        intent_counts=IntegrationOperationCounts(
            applied=0,
            skipped=0,
            failed=1,
            unverified=0,
        ),
        effect_counts=IntegrationOperationCounts(
            applied=1,
            skipped=0,
            failed=1,
            unverified=0,
        ),
    )
