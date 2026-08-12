# apps/api/services/audit_events/integration_operation_detail.py

"""Bounded, provider-neutral evidence for audited integration operations."""

import json
from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

type AuditDetailValue = (
    str | int | float | bool | list["AuditDetailValue"] | dict[str, "AuditDetailValue"] | None
)
type IntegrationOperationOutcomeStatus = Literal["applied", "skipped", "failed", "unverified"]
type IntegrationOperationEffectStatus = Literal["applied", "failed", "unverified"]

MAX_INTEGRATION_OPERATION_DETAIL_BYTES = 1_000_000
MAX_INTEGRATION_OPERATION_GROUPS = 500
MAX_INTEGRATION_OPERATION_ITEMS = 2_500


class IntegrationOperationTarget(BaseModel):
    """The provider entity against which an operation was executed."""

    model_config = ConfigDict(extra="forbid")

    entity_type: str = Field(min_length=1, max_length=100)
    external_id: str = Field(min_length=1, max_length=1_000)
    display_name: str | None = Field(default=None, max_length=500)
    integration_resource_id: str | None = Field(default=None, max_length=100)
    attributes: dict[str, AuditDetailValue] = Field(default_factory=dict, max_length=32)


class IntegrationOperationIntent(BaseModel):
    """One requested item within a bounded target/action group."""

    model_config = ConfigDict(extra="forbid")

    fields: dict[str, AuditDetailValue] = Field(min_length=1, max_length=32)


class IntegrationOperationIntentGroup(BaseModel):
    """Ordered requested items sharing one target and action."""

    model_config = ConfigDict(extra="forbid")

    key: str = Field(min_length=1, max_length=500)
    action: str = Field(min_length=1, max_length=64)
    entity_type: str = Field(min_length=1, max_length=100)
    external_id: str | None = Field(default=None, max_length=1_000)
    display_name: str | None = Field(default=None, max_length=500)
    fields: dict[str, AuditDetailValue] = Field(default_factory=dict, max_length=32)
    items: list[IntegrationOperationIntent] = Field(
        min_length=1,
        max_length=MAX_INTEGRATION_OPERATION_ITEMS,
    )


class IntegrationOperationEffect(BaseModel):
    """One concrete provider effect dispatched for a requested item."""

    model_config = ConfigDict(extra="forbid")

    status: IntegrationOperationEffectStatus
    fields: dict[str, AuditDetailValue] = Field(default_factory=dict, max_length=32)
    external_ref: str | None = Field(default=None, max_length=1_000)
    error_code: str | None = Field(default=None, max_length=100)

    @model_validator(mode="after")
    def validate_evidence(self) -> Self:
        if self.status == "applied":
            if self.error_code is not None:
                raise ValueError("Applied effects cannot carry an error code")
        elif self.external_ref is not None or self.error_code is None:
            raise ValueError("Failed and unverified effects require only an error code")
        return self


class IntegrationOperationOutcome(BaseModel):
    """The terminal result for one requested item."""

    model_config = ConfigDict(extra="forbid")

    intent_index: int = Field(ge=0)
    status: IntegrationOperationOutcomeStatus
    fields: dict[str, AuditDetailValue] = Field(default_factory=dict, max_length=32)
    effects: list[IntegrationOperationEffect] = Field(
        default_factory=list,
        max_length=MAX_INTEGRATION_OPERATION_ITEMS,
    )

    @model_validator(mode="after")
    def validate_status_against_effects(self) -> Self:
        effect_statuses = {effect.status for effect in self.effects}
        if self.status == "skipped":
            if self.effects:
                raise ValueError("Skipped intents cannot carry concrete effects")
        elif not self.effects:
            raise ValueError("Non-skipped intents require concrete effects")
        elif self.status == "applied" and effect_statuses != {"applied"}:
            raise ValueError("Applied intents require only applied effects")
        elif self.status == "failed" and (
            "failed" not in effect_statuses or "unverified" in effect_statuses
        ):
            raise ValueError("Failed intents require a failed effect and no unverified effects")
        elif self.status == "unverified" and "unverified" not in effect_statuses:
            raise ValueError("Unverified intents require an unverified effect")
        return self


class IntegrationOperationOutcomeGroup(BaseModel):
    """Terminal outcomes aligned to one requested intent group."""

    model_config = ConfigDict(extra="forbid")

    key: str = Field(min_length=1, max_length=500)
    outcomes: list[IntegrationOperationOutcome] = Field(
        min_length=1,
        max_length=MAX_INTEGRATION_OPERATION_ITEMS,
    )


class IntegrationOperationCounts(BaseModel):
    """Closed counts for intent or concrete-effect outcomes."""

    model_config = ConfigDict(extra="forbid")

    applied: int = Field(ge=0)
    skipped: int = Field(ge=0)
    failed: int = Field(ge=0)
    unverified: int = Field(ge=0)


class _IntegrationOperationDetailBase(BaseModel):
    model_config = ConfigDict(extra="forbid")

    target: IntegrationOperationTarget
    intent_groups: list[IntegrationOperationIntentGroup] = Field(
        min_length=1,
        max_length=MAX_INTEGRATION_OPERATION_GROUPS,
    )

    @model_validator(mode="after")
    def validate_common_bounds(self) -> Self:
        keys = [group.key for group in self.intent_groups]
        if len(keys) != len(set(keys)):
            raise ValueError("Integration operation intent group keys must be unique")
        if sum(len(group.items) for group in self.intent_groups) > MAX_INTEGRATION_OPERATION_ITEMS:
            raise ValueError("Integration operation detail exceeds the 2,500-item limit")
        _enforce_serialized_size(self)
        return self


class PendingIntegrationOperationDetail(_IntegrationOperationDetailBase):
    """Requested intent persisted before provider operation dispatch."""

    phase: Literal["pending"] = "pending"


class TerminalIntegrationOperationDetail(_IntegrationOperationDetailBase):
    """Requested intent plus exact observed terminal outcomes and effects."""

    phase: Literal["terminal"] = "terminal"
    outcome_groups: list[IntegrationOperationOutcomeGroup] = Field(
        min_length=1,
        max_length=MAX_INTEGRATION_OPERATION_GROUPS,
    )
    intent_counts: IntegrationOperationCounts
    effect_counts: IntegrationOperationCounts

    @model_validator(mode="after")
    def validate_terminal_evidence(self) -> Self:
        intent_by_key = {group.key: group for group in self.intent_groups}
        if [group.key for group in self.outcome_groups] != list(intent_by_key):
            raise ValueError("Outcome groups must align exactly with ordered intent groups")

        outcomes: list[IntegrationOperationOutcome] = []
        effects: list[IntegrationOperationEffect] = []
        for group in self.outcome_groups:
            expected_indices = list(range(len(intent_by_key[group.key].items)))
            actual_indices = [outcome.intent_index for outcome in group.outcomes]
            if actual_indices != expected_indices:
                raise ValueError("Outcomes must align exactly with ordered intent items")
            outcomes.extend(group.outcomes)
            effects.extend(effect for outcome in group.outcomes for effect in outcome.effects)

        if len(effects) > MAX_INTEGRATION_OPERATION_ITEMS:
            raise ValueError("Integration operation detail exceeds the 2,500-effect limit")

        if self.intent_counts != _counts_for(item.status for item in outcomes):
            raise ValueError("Intent counts do not match terminal outcomes")
        expected_effect_counts = _counts_for(effect.status for effect in effects)
        if expected_effect_counts.skipped != 0 or self.effect_counts != expected_effect_counts:
            raise ValueError("Effect counts do not match concrete effects")
        _enforce_serialized_size(self)
        return self


type IntegrationOperationDetail = Annotated[
    PendingIntegrationOperationDetail | TerminalIntegrationOperationDetail,
    Field(discriminator="phase"),
]


def terminal_applied_operation_detail(
    pending: PendingIntegrationOperationDetail,
    *,
    external_ref: str | None = None,
) -> TerminalIntegrationOperationDetail:
    """Close one single-item operation with one confirmed provider effect."""
    if len(pending.intent_groups) != 1 or len(pending.intent_groups[0].items) != 1:
        raise ValueError("Single-effect evidence requires exactly one requested item")
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
                        status="applied",
                        effects=[
                            IntegrationOperationEffect(
                                status="applied",
                                external_ref=external_ref,
                            )
                        ],
                    )
                ],
            )
        ],
        intent_counts=IntegrationOperationCounts(
            applied=1,
            skipped=0,
            failed=0,
            unverified=0,
        ),
        effect_counts=IntegrationOperationCounts(
            applied=1,
            skipped=0,
            failed=0,
            unverified=0,
        ),
    )


def _counts_for(statuses) -> IntegrationOperationCounts:
    values = tuple(statuses)
    return IntegrationOperationCounts(
        applied=values.count("applied"),
        skipped=values.count("skipped"),
        failed=values.count("failed"),
        unverified=values.count("unverified"),
    )


def _enforce_serialized_size(detail: BaseModel) -> None:
    serialized = json.dumps(
        detail.model_dump(mode="json"),
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode()
    if len(serialized) > MAX_INTEGRATION_OPERATION_DETAIL_BYTES:
        raise ValueError("Integration operation audit detail exceeds the 1,000,000-byte limit")
