# apps/api/integrations/google_search_console/tools/utils/mutation_evidence.py

"""Build Search Console mutation evidence for the shared audit contract."""

from collections.abc import Iterable, Mapping, Sequence
from typing import Any, Literal

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
)
from services.integrations.context.domain import ResolvedContextEntry


def site_target(entry: ResolvedContextEntry) -> IntegrationOperationTarget:
    """Builds the Search Console site target used by write evidence."""
    return IntegrationOperationTarget(
        entity_type="google_search_console_site",
        external_id=entry.external_id,
        display_name=entry.display_name,
        integration_resource_id=str(entry.integration_resource_id),
    )


def sitemap_pending_detail(
    entry: ResolvedContextEntry,
    items: Sequence[Mapping[str, Any]],
) -> PendingIntegrationOperationDetail:
    """Builds the ordered sitemap intent recorded before provider dispatch."""
    return PendingIntegrationOperationDetail(
        target=site_target(entry),
        intent_groups=[
            IntegrationOperationIntentGroup(
                key="sitemap:submit",
                action="submit",
                entity_type="google_search_console_sitemap",
                items=[
                    IntegrationOperationIntent(
                        fields={
                            "sitemap_url": str(item["sitemap_url"]),
                            "previously_submitted": bool(item["previously_submitted"]),
                        }
                    )
                    for item in items
                ],
            )
        ],
    )


def indexing_pending_detail(
    entry: ResolvedContextEntry,
    items: Sequence[Mapping[str, Any]],
) -> PendingIntegrationOperationDetail:
    """Builds the ordered URL notification intent recorded before dispatch."""
    return PendingIntegrationOperationDetail(
        target=site_target(entry),
        intent_groups=[
            IntegrationOperationIntentGroup(
                key="url:notify",
                action="notify",
                entity_type="google_search_console_url",
                items=[
                    IntegrationOperationIntent(
                        fields={
                            "url": str(item["url"]),
                            "notification_type": str(item["notification_type"]),
                            "page_type": str(item["page_type"]),
                        }
                    )
                    for item in items
                ],
            )
        ],
    )


def sitemap_terminal_detail(
    pending: PendingIntegrationOperationDetail,
    outcomes: Sequence[Mapping[str, Any]],
) -> TerminalIntegrationOperationDetail:
    """Closes every sitemap intent with its concrete provider effect."""
    return _terminal_detail(
        pending,
        outcomes,
        evidence_name="Sitemap",
        external_ref_field="sitemap_url",
        applied_outcome="submitted",
        result_fields=("status_read", "last_submitted", "is_pending", "warnings", "errors"),
    )


def indexing_terminal_detail(
    pending: PendingIntegrationOperationDetail,
    outcomes: Sequence[Mapping[str, Any]],
) -> TerminalIntegrationOperationDetail:
    """Closes every URL notification intent with its provider effect."""
    return _terminal_detail(
        pending,
        outcomes,
        evidence_name="Indexing",
        external_ref_field="url",
        applied_outcome="notified",
        result_fields=("notify_time",),
    )


def _terminal_detail(
    pending: PendingIntegrationOperationDetail,
    outcomes: Sequence[Mapping[str, Any]],
    *,
    evidence_name: str,
    external_ref_field: str,
    applied_outcome: str,
    result_fields: tuple[str, ...],
) -> TerminalIntegrationOperationDetail:
    if len(pending.intent_groups) != 1:
        raise ValueError(f"{evidence_name} evidence requires one intent group")
    group = pending.intent_groups[0]
    if len(group.items) != len(outcomes):
        raise ValueError(f"{evidence_name} outcomes do not account for every audit intent")

    terminal_outcomes: list[IntegrationOperationOutcome] = []
    for index, (intent, outcome) in enumerate(zip(group.items, outcomes, strict=True)):
        external_ref = str(outcome[external_ref_field])
        if intent.fields.get(external_ref_field) != external_ref:
            raise ValueError(f"{evidence_name} outcomes do not align with ordered audit intents")
        status = _intent_status(str(outcome["outcome"]), applied_outcome=applied_outcome)
        error_code = str(outcome["error_code"]) if outcome.get("error_code") else None
        effect = (
            IntegrationOperationEffect(status="applied", external_ref=external_ref[:1_000])
            if status == "applied"
            else IntegrationOperationEffect(
                status=status,
                error_code=error_code or "integration_error",
            )
        )
        terminal_outcomes.append(
            IntegrationOperationOutcome(
                intent_index=index,
                status=status,
                fields={field: outcome.get(field) for field in result_fields},
                effects=[effect],
            )
        )
    counts = _counts(outcome.status for outcome in terminal_outcomes)
    return TerminalIntegrationOperationDetail(
        target=pending.target,
        intent_groups=pending.intent_groups,
        outcome_groups=[
            IntegrationOperationOutcomeGroup(key=group.key, outcomes=terminal_outcomes)
        ],
        intent_counts=counts,
        effect_counts=counts,
    )


def audit_status(detail: TerminalIntegrationOperationDetail) -> AuditStatus:
    """Derives one terminal audit status from mutation outcome counts."""
    counts = detail.intent_counts
    if counts.unverified:
        return AuditStatus.UNVERIFIED
    if counts.failed:
        return AuditStatus.PARTIAL if counts.applied or counts.skipped else AuditStatus.FAILURE
    return AuditStatus.SUCCESS


def _intent_status(
    value: str,
    *,
    applied_outcome: str,
) -> Literal["applied", "failed", "unverified"]:
    if value == applied_outcome:
        return "applied"
    if value == "failed":
        return "failed"
    if value == "unverified":
        return "unverified"
    raise ValueError("Mutation outcome is not terminal")


def _counts(statuses: Iterable[str]) -> IntegrationOperationCounts:
    values = tuple(statuses)
    return IntegrationOperationCounts(
        applied=values.count("applied"),
        skipped=values.count("skipped"),
        failed=values.count("failed"),
        unverified=values.count("unverified"),
    )
