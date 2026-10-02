# apps/api/integrations/meta_ads/tools/utils/mutation_evidence.py

"""Project the Meta Ads mutation ledger into the platform evidence contract."""

from collections.abc import Iterable

from services.audit_events import (
    AuditStatus,
    IntegrationOperationCounts,
    IntegrationOperationEffect,
    IntegrationOperationOutcome,
    IntegrationOperationOutcomeGroup,
    IntegrationOperationTarget,
    PendingIntegrationOperationDetail,
    TerminalIntegrationOperationDetail,
)
from services.integrations.context.domain import ResolvedContextEntry

from ...operations.mutations import MetaAdsMutationLedger


def meta_ads_account_target(entry: ResolvedContextEntry) -> IntegrationOperationTarget:
    """Builds the ad account target used by Meta Ads write evidence."""
    return IntegrationOperationTarget(
        entity_type="meta_ads_ad_account",
        external_id=entry.external_id,
        display_name=entry.display_name,
        integration_resource_id=str(entry.integration_resource_id),
    )


def terminal_operation_detail(
    pending: PendingIntegrationOperationDetail,
    ledger: MetaAdsMutationLedger,
    *,
    identity_key: str,
) -> TerminalIntegrationOperationDetail:
    """Attaches each ledger parent to the pending intent with the same identity value."""
    locations: dict[str, tuple[int, int]] = {}
    for group_index, group in enumerate(pending.intent_groups):
        for intent_index, intent in enumerate(group.items):
            identity = str({**group.fields, **intent.fields}.get(identity_key) or "")
            if not identity or identity in locations:
                raise ValueError("Meta Ads audit intents do not match unique ledger identities")
            locations[identity] = (group_index, intent_index)

    grouped: list[list[IntegrationOperationOutcome | None]] = [
        [None] * len(group.items) for group in pending.intent_groups
    ]
    for parent in ledger.parents:
        location = locations.pop(dict(parent.identity).get(identity_key, ""), None)
        if location is None:
            raise ValueError("Meta Ads ledger contains an unknown audit intent")
        group_index, intent_index = location
        grouped[group_index][intent_index] = IntegrationOperationOutcome(
            intent_index=intent_index,
            status=parent.outcome,
            fields={"reason": parent.skip_reason} if parent.skip_reason else {},
            effects=[
                IntegrationOperationEffect(
                    status=effect.outcome,
                    fields=dict(effect.fields),
                    external_ref=effect.external_ref,
                    error_code=effect.error_code,
                )
                for effect in parent.effects
            ],
        )
    if locations:
        raise ValueError("Meta Ads ledger does not account for every audit intent")

    outcome_groups = [
        IntegrationOperationOutcomeGroup(
            key=group.key, outcomes=[item for item in outcomes if item is not None]
        )
        for group, outcomes in zip(pending.intent_groups, grouped, strict=True)
    ]
    outcomes = [outcome for group in outcome_groups for outcome in group.outcomes]
    return TerminalIntegrationOperationDetail(
        target=pending.target,
        intent_groups=pending.intent_groups,
        outcome_groups=outcome_groups,
        intent_counts=_counts(outcome.status for outcome in outcomes),
        effect_counts=_counts(effect.status for outcome in outcomes for effect in outcome.effects),
    )


def audit_status(detail: TerminalIntegrationOperationDetail) -> AuditStatus:
    """Derives one terminal audit status from intent and effect counts."""
    intents = detail.intent_counts
    effects = detail.effect_counts
    if intents.unverified or effects.unverified:
        return AuditStatus.UNVERIFIED
    if intents.failed:
        # A parent with one applied effect still changed Meta, so only all-failed is a failure.
        if intents.applied or intents.skipped or effects.applied:
            return AuditStatus.PARTIAL
        return AuditStatus.FAILURE
    return AuditStatus.SUCCESS


def _counts(statuses: Iterable[str]) -> IntegrationOperationCounts:
    values = tuple(statuses)
    return IntegrationOperationCounts(
        applied=values.count("applied"),
        skipped=values.count("skipped"),
        failed=values.count("failed"),
        unverified=values.count("unverified"),
    )
