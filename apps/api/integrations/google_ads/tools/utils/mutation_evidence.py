# apps/api/integrations/google_ads/tools/utils/mutation_evidence.py

"""Project the Google Ads mutation ledger into the platform evidence contract."""

from collections.abc import Iterable

from integrations.google_ads.operations.mutation_outcomes import (
    GoogleAdsMutationLedger,
    thaw_fields,
)
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


def google_ads_account_target(entry: ResolvedContextEntry) -> IntegrationOperationTarget:
    """Build the provider-account target used by Google Ads write evidence."""
    return IntegrationOperationTarget(
        entity_type="google_ads_account",
        external_id=entry.external_id,
        display_name=entry.display_name,
        integration_resource_id=str(entry.integration_resource_id),
    )


def terminal_operation_detail(
    pending: PendingIntegrationOperationDetail,
    ledger: GoogleAdsMutationLedger,
) -> TerminalIntegrationOperationDetail:
    """Attach every ledger parent and effect to its exact requested intent."""
    identity_keys = tuple(key for key, _value in ledger.parents[0].identity)
    locations: dict[tuple[str, ...], tuple[int, int]] = {}
    for group_index, group in enumerate(pending.intent_groups):
        for intent_index, intent in enumerate(group.items):
            identity = tuple(str(intent.fields.get(key, "")) for key in identity_keys)
            if not all(identity) or identity in locations:
                raise ValueError("Google Ads audit intents do not match unique ledger identities")
            locations[identity] = (group_index, intent_index)

    grouped: list[list[IntegrationOperationOutcome | None]] = [
        [None] * len(group.items) for group in pending.intent_groups
    ]
    for parent in ledger.parents:
        identity_fields = thaw_fields(parent.identity)
        identity = tuple(identity_fields[key] for key in identity_keys)
        location = locations.pop(identity, None)
        if location is None:
            raise ValueError("Google Ads ledger contains an unknown audit intent")
        group_index, intent_index = location
        effects = [
            IntegrationOperationEffect(
                status=effect.outcome,
                fields=(
                    {}
                    if thaw_fields(effect.fields) == identity_fields
                    else thaw_fields(effect.fields)
                ),
                external_ref=effect.external_ref,
                error_code=effect.error_code,
            )
            for effect in parent.effects
        ]
        grouped[group_index][intent_index] = IntegrationOperationOutcome(
            intent_index=intent_index,
            status=(
                "skipped"
                if parent.decision == "skipped"
                else "unverified"
                if any(effect.status == "unverified" for effect in effects)
                else "failed"
                if any(effect.status == "failed" for effect in effects)
                else "applied"
            ),
            fields={"reason": parent.skip_reason} if parent.skip_reason else {},
            effects=effects,
        )
    if locations or any(item is None for outcomes in grouped for item in outcomes):
        raise ValueError("Google Ads ledger does not account for every audit intent")

    outcome_groups = [
        IntegrationOperationOutcomeGroup(
            key=intent_group.key,
            outcomes=[item for item in outcomes if item is not None],
        )
        for intent_group, outcomes in zip(pending.intent_groups, grouped, strict=True)
    ]
    intent_statuses = [outcome.status for group in outcome_groups for outcome in group.outcomes]
    effect_statuses = [
        effect.status
        for group in outcome_groups
        for outcome in group.outcomes
        for effect in outcome.effects
    ]
    return TerminalIntegrationOperationDetail(
        target=pending.target,
        intent_groups=pending.intent_groups,
        outcome_groups=outcome_groups,
        intent_counts=_counts(intent_statuses),
        effect_counts=_counts(effect_statuses),
    )


def audit_status(detail: TerminalIntegrationOperationDetail) -> AuditStatus:
    """Derive one terminal audit status from independently validated counts."""
    intents = detail.intent_counts
    effects = detail.effect_counts
    if intents.unverified or effects.unverified:
        return AuditStatus.UNVERIFIED
    if intents.failed:
        if intents.failed == _count_total(intents) and effects.applied == 0:
            return AuditStatus.FAILURE
        return AuditStatus.PARTIAL
    return AuditStatus.SUCCESS


def _counts(statuses: Iterable[str]) -> IntegrationOperationCounts:
    values = tuple(statuses)
    return IntegrationOperationCounts(
        applied=values.count("applied"),
        skipped=values.count("skipped"),
        failed=values.count("failed"),
        unverified=values.count("unverified"),
    )


def _count_total(counts: IntegrationOperationCounts) -> int:
    return counts.applied + counts.skipped + counts.failed + counts.unverified
