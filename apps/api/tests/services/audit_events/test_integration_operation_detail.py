"""Contracts for provider-neutral integration-operation evidence."""

import pytest
from pydantic import ValidationError

from services.audit_events import (
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


def _target() -> IntegrationOperationTarget:
    return IntegrationOperationTarget(
        entity_type="campaign",
        external_id="campaign-1",
        attributes={"channel": "search"},
    )


def _intent_group(*, count: int = 1) -> IntegrationOperationIntentGroup:
    return IntegrationOperationIntentGroup(
        key="campaign-1:update",
        action="update",
        entity_type="campaign_targeting",
        external_id="campaign-1",
        display_name="Brand Search",
        items=[IntegrationOperationIntent(fields={"row_id": str(index)}) for index in range(count)],
    )


def _counts(
    *,
    applied: int = 0,
    skipped: int = 0,
    failed: int = 0,
    unverified: int = 0,
) -> IntegrationOperationCounts:
    return IntegrationOperationCounts(
        applied=applied,
        skipped=skipped,
        failed=failed,
        unverified=unverified,
    )


def test_pending_detail_contains_intent_without_terminal_fields() -> None:
    detail = PendingIntegrationOperationDetail(target=_target(), intent_groups=[_intent_group()])

    assert detail.model_dump(mode="json") == {
        "target": {
            "entity_type": "campaign",
            "external_id": "campaign-1",
            "display_name": None,
            "integration_resource_id": None,
            "attributes": {"channel": "search"},
        },
        "intent_groups": [
            {
                "key": "campaign-1:update",
                "action": "update",
                "entity_type": "campaign_targeting",
                "external_id": "campaign-1",
                "display_name": "Brand Search",
                "fields": {},
                "items": [{"fields": {"row_id": "0"}}],
            }
        ],
        "phase": "pending",
    }


def test_single_applied_detail_closes_one_item_without_copying_identity_fields() -> None:
    pending = PendingIntegrationOperationDetail(target=_target(), intent_groups=[_intent_group()])

    detail = terminal_applied_operation_detail(pending, external_ref="records/1")

    outcome = detail.outcome_groups[0].outcomes[0]
    assert outcome.status == "applied"
    assert outcome.effects[0].fields == {}
    assert outcome.effects[0].external_ref == "records/1"
    assert detail.intent_counts == _counts(applied=1)
    assert detail.effect_counts == _counts(applied=1)


def test_terminal_detail_validates_intent_and_effect_counts_independently() -> None:
    intents = _intent_group(count=4)
    outcomes = IntegrationOperationOutcomeGroup(
        key=intents.key,
        outcomes=[
            IntegrationOperationOutcome(
                intent_index=0,
                status="applied",
                effects=[
                    IntegrationOperationEffect(
                        status="applied",
                        fields={"criterion_id": "1"},
                        external_ref="criteria/1",
                    )
                ],
            ),
            IntegrationOperationOutcome(intent_index=1, status="skipped"),
            IntegrationOperationOutcome(
                intent_index=2,
                status="failed",
                effects=[
                    IntegrationOperationEffect(
                        status="failed",
                        fields={"criterion_id": "2"},
                        error_code="INVALID",
                    )
                ],
            ),
            IntegrationOperationOutcome(
                intent_index=3,
                status="unverified",
                effects=[
                    IntegrationOperationEffect(
                        status="unverified",
                        fields={"criterion_id": "3"},
                        error_code="UNKNOWN_RESULT",
                    )
                ],
            ),
        ],
    )

    detail = TerminalIntegrationOperationDetail(
        target=_target(),
        intent_groups=[intents],
        outcome_groups=[outcomes],
        intent_counts=_counts(applied=1, skipped=1, failed=1, unverified=1),
        effect_counts=_counts(applied=1, failed=1, unverified=1),
    )

    assert detail.phase == "terminal"
    assert detail.intent_counts.skipped == 1
    assert detail.effect_counts.skipped == 0


def test_any_parent_can_retain_ordered_concrete_effects() -> None:
    intents = _intent_group()
    detail = TerminalIntegrationOperationDetail(
        target=_target(),
        intent_groups=[intents],
        outcome_groups=[
            IntegrationOperationOutcomeGroup(
                key=intents.key,
                outcomes=[
                    IntegrationOperationOutcome(
                        intent_index=0,
                        status="failed",
                        effects=[
                            IntegrationOperationEffect(
                                status="applied",
                                fields={"match_type": "EXACT"},
                                external_ref="criteria/1",
                            ),
                            IntegrationOperationEffect(
                                status="failed",
                                fields={"match_type": "PHRASE"},
                                error_code="NOT_REMOVED",
                            ),
                        ],
                    )
                ],
            )
        ],
        intent_counts=_counts(failed=1),
        effect_counts=_counts(applied=1, failed=1),
    )

    assert [effect.status for effect in detail.outcome_groups[0].outcomes[0].effects] == [
        "applied",
        "failed",
    ]


@pytest.mark.parametrize(
    ("outcome", "match"),
    [
        (
            IntegrationOperationOutcome(
                intent_index=1,
                status="applied",
                effects=[IntegrationOperationEffect(status="applied", fields={"id": "1"})],
            ),
            "align exactly",
        ),
        (IntegrationOperationOutcome(intent_index=0, status="skipped"), "Intent counts"),
    ],
)
def test_terminal_detail_rejects_malformed_alignment_and_counts(
    outcome: IntegrationOperationOutcome,
    match: str,
) -> None:
    intents = _intent_group()
    with pytest.raises(ValidationError, match=match):
        TerminalIntegrationOperationDetail(
            target=_target(),
            intent_groups=[intents],
            outcome_groups=[IntegrationOperationOutcomeGroup(key=intents.key, outcomes=[outcome])],
            intent_counts=_counts(applied=1),
            effect_counts=_counts(applied=1),
        )


def test_detail_accepts_2500_nested_items_but_rejects_a_2501st() -> None:
    PendingIntegrationOperationDetail(target=_target(), intent_groups=[_intent_group(count=2_500)])

    with pytest.raises(ValidationError, match="2,500-item limit"):
        PendingIntegrationOperationDetail(
            target=_target(),
            intent_groups=[
                _intent_group(count=2_500),
                _intent_group().model_copy(update={"key": "campaign-2:update"}),
            ],
        )


def test_terminal_detail_rejects_more_than_2500_concrete_effects() -> None:
    intents = _intent_group(count=2)
    effects = [
        IntegrationOperationEffect(status="applied", fields={"id": str(index)})
        for index in range(2_501)
    ]

    with pytest.raises(ValidationError, match="2,500-effect limit"):
        TerminalIntegrationOperationDetail(
            target=_target(),
            intent_groups=[intents],
            outcome_groups=[
                IntegrationOperationOutcomeGroup(
                    key=intents.key,
                    outcomes=[
                        IntegrationOperationOutcome(
                            intent_index=0,
                            status="applied",
                            effects=effects[:1_251],
                        ),
                        IntegrationOperationOutcome(
                            intent_index=1,
                            status="applied",
                            effects=effects[1_251:],
                        ),
                    ],
                )
            ],
            intent_counts=_counts(applied=2),
            effect_counts=_counts(applied=2_501),
        )


def test_detail_rejects_more_than_500_groups_and_oversized_payloads() -> None:
    groups = [
        IntegrationOperationIntentGroup(
            key=f"group-{index}",
            action="update",
            entity_type="record",
            items=[IntegrationOperationIntent(fields={"id": str(index)})],
        )
        for index in range(501)
    ]
    with pytest.raises(ValidationError, match="at most 500 items"):
        PendingIntegrationOperationDetail(target=_target(), intent_groups=groups)

    with pytest.raises(ValidationError, match="1,000,000-byte limit"):
        PendingIntegrationOperationDetail(
            target=_target(),
            intent_groups=[
                IntegrationOperationIntentGroup(
                    key="large",
                    action="update",
                    entity_type="record",
                    items=[
                        IntegrationOperationIntent(fields={"provider_payload": "x" * 1_000_000})
                    ],
                )
            ],
        )
