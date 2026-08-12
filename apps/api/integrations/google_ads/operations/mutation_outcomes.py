# apps/api/integrations/google_ads/operations/mutation_outcomes.py

"""Exact provider-local accounting for Google Ads mutation outcomes."""

from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Literal

type MutationEffectOutcome = Literal["applied", "failed", "unverified"]
type MutationParentDecision = Literal["submit", "skipped"]
type FrozenFields = tuple[tuple[str, str], ...]


def freeze_fields(fields: Mapping[str, object]) -> FrozenFields:
    """Freeze bounded scalar identity/evidence fields in insertion order."""
    frozen: list[tuple[str, str]] = []
    for key, value in fields.items():
        if not isinstance(key, str) or not key or not isinstance(value, str) or not value:
            raise ValueError("Google Ads mutation fields require non-empty strings")
        if any(existing_key == key for existing_key, _ in frozen):
            raise ValueError("Google Ads mutation fields require unique keys")
        frozen.append((key, value))
    if not frozen:
        raise ValueError("Google Ads mutation fields cannot be empty")
    return tuple(frozen)


def thaw_fields(fields: FrozenFields) -> dict[str, str]:
    return dict(fields)


@dataclass(frozen=True, slots=True)
class GoogleAdsMutationEffect:
    """One concrete provider slot dispatched for a requested parent intent."""

    slot: int
    fields: FrozenFields
    outcome: MutationEffectOutcome
    external_ref: str | None = None
    error_code: str | None = None
    message: str | None = None

    def __post_init__(self) -> None:
        if self.slot < 0:
            raise ValueError("Google Ads mutation effect slot cannot be negative")
        freeze_fields(thaw_fields(self.fields))
        if self.outcome not in {"applied", "failed", "unverified"}:
            raise ValueError("Google Ads mutation effect outcome is invalid")
        if self.outcome == "applied":
            if not self.external_ref or self.error_code is not None or self.message is not None:
                raise ValueError("Applied Google Ads effects require only an external reference")
        elif self.external_ref is not None:
            raise ValueError("Non-applied Google Ads effects cannot have an external reference")
        elif not self.error_code or not self.message:
            raise ValueError("Failed or unverified Google Ads effects require diagnostics")


@dataclass(frozen=True, slots=True)
class GoogleAdsMutationParent:
    """One normalized requested mutation identity and its concrete effects."""

    identity: FrozenFields
    decision: MutationParentDecision
    effects: tuple[GoogleAdsMutationEffect, ...] = ()
    skip_reason: str | None = None

    def __post_init__(self) -> None:
        freeze_fields(thaw_fields(self.identity))
        if self.decision not in {"submit", "skipped"}:
            raise ValueError("Google Ads mutation parent decision is invalid")
        if self.decision == "skipped":
            if not self.skip_reason or self.effects:
                raise ValueError("Skipped Google Ads parents require a reason and no effects")
        elif self.skip_reason is not None or not self.effects:
            raise ValueError("Submitted Google Ads parents require effects and no skip reason")


@dataclass(frozen=True, slots=True)
class GoogleAdsMutationProjection:
    """Names needed to retain one mutation family's existing v1 result shape."""

    applied_key: str
    skipped_key: str
    errors_key: str
    resource_names: bool = True
    error_scope: str | None = None


@dataclass(frozen=True, slots=True)
class GoogleAdsKeywordMutationSpec:
    """Frozen result vocabulary for one negative-keyword owner kind."""

    family: str
    errors_key: str
    add_resource_names: bool = True
    remove_resource_names: bool = True
    error_scope: str | None = None


SHARED_SET_KEYWORD_MUTATION_SPEC = GoogleAdsKeywordMutationSpec(
    family="shared_set_keywords",
    errors_key="keyword_errors",
    add_resource_names=False,
    error_scope="keyword",
)
CAMPAIGN_KEYWORD_MUTATION_SPEC = GoogleAdsKeywordMutationSpec(
    family="campaign_negative_keywords",
    errors_key="campaign_errors",
)
AD_GROUP_KEYWORD_MUTATION_SPEC = GoogleAdsKeywordMutationSpec(
    family="ad_group_negative_keywords",
    errors_key="ad_group_errors",
)


@dataclass(frozen=True, slots=True, eq=False)
class GoogleAdsMutationLedger(Mapping[str, Any]):
    """Ordered exact accounting for one Google Ads mutation operation."""

    family: str
    action: str
    parents: tuple[GoogleAdsMutationParent, ...]
    projection: GoogleAdsMutationProjection

    def __post_init__(self) -> None:
        if not self.family or not self.action or not self.parents:
            raise ValueError("Google Ads mutation ledgers require family, action, and parents")
        identities = [parent.identity for parent in self.parents]
        if len(set(identities)) != len(identities):
            raise ValueError("Google Ads mutation parents must be unique")
        effects = [effect for parent in self.parents for effect in parent.effects]
        slots = [effect.slot for effect in effects]
        if len(set(slots)) != len(slots) or sorted(slots) != list(range(len(slots))):
            raise ValueError("Google Ads mutation effects must account for every slot exactly once")
        concrete = [effect.fields for effect in effects]
        if len(set(concrete)) != len(concrete):
            raise ValueError("Google Ads mutation effects must have unique concrete identities")

    @property
    def effects(self) -> tuple[GoogleAdsMutationEffect, ...]:
        return tuple(effect for parent in self.parents for effect in parent.effects)

    @property
    def intent_counts(self) -> dict[str, int]:
        return {
            "requested": len(self.parents),
            "submitted": sum(parent.decision == "submit" for parent in self.parents),
            "skipped": sum(parent.decision == "skipped" for parent in self.parents),
        }

    @property
    def effect_counts(self) -> dict[str, int]:
        return {
            outcome: sum(effect.outcome == outcome for effect in self.effects)
            for outcome in ("applied", "failed", "unverified")
        }

    @property
    def external_refs(self) -> tuple[str, ...]:
        return tuple(
            effect.external_ref
            for effect in self.effects
            if effect.outcome == "applied" and effect.external_ref is not None
        )

    def parent_for_slot(self, slot: int) -> GoogleAdsMutationParent:
        for parent in self.parents:
            if any(effect.slot == slot for effect in parent.effects):
                return parent
        raise KeyError(slot)

    def require_verified(self) -> None:
        """Fail after dispatch when any concrete provider slot remains ambiguous."""
        if any(effect.outcome == "unverified" for effect in self.effects):
            raise ValueError("Google Ads mutation outcome could not be verified exactly")

    def keyword_outcomes(self, *, entity_id_key: str) -> dict[str, list[dict[str, str]]]:
        """Project ordered exact keyword evidence for scoped transcript/audit rows."""
        outcomes: dict[str, list[dict[str, str]]] = {}
        for parent in self.parents:
            parent_fields = thaw_fields(parent.identity)
            entity_id = parent_fields.get(entity_id_key)
            if not entity_id:
                raise ValueError("Scoped keyword ledger parent is missing its entity identity")
            rows = outcomes.setdefault(entity_id, [])
            if parent.decision == "skipped":
                rows.append(
                    {
                        "text": parent_fields["text"],
                        "match_type": parent_fields["match_type"],
                        "outcome": self.projection.skipped_key,
                    }
                )
                continue
            for effect in parent.effects:
                fields = thaw_fields(effect.fields)
                row = {
                    "text": fields["text"],
                    "match_type": fields["match_type"],
                    "outcome": (
                        self.projection.applied_key if effect.outcome == "applied" else "failed"
                    ),
                }
                if effect.external_ref is not None:
                    row["external_ref"] = effect.external_ref
                if effect.error_code is not None:
                    row["error_code"] = effect.error_code[:100]
                rows.append(row)
        return outcomes

    def result(self) -> dict[str, Any]:
        """Project the frozen v1 operation result without recounting provider payloads."""
        applied: list[dict[str, str]] = []
        failed: list[dict[str, str]] = []
        skipped: list[dict[str, str]] = []
        for parent in self.parents:
            parent_fields = thaw_fields(parent.identity)
            if parent.decision == "skipped":
                skipped.append(parent_fields)
                continue
            for effect in parent.effects:
                fields = thaw_fields(effect.fields)
                if effect.outcome == "applied":
                    applied.append({**fields, "resource_name": effect.external_ref or ""})
                else:
                    error = {
                        **fields,
                        "message": effect.message or "",
                        "error_code": effect.error_code or "",
                    }
                    if self.projection.error_scope is not None:
                        error = {"scope": self.projection.error_scope, **error}
                    failed.append(error)
        result: dict[str, Any] = {
            self.projection.applied_key: applied,
            self.projection.skipped_key: skipped,
            self.projection.errors_key: failed,
        }
        if self.family == "negative_keyword_lists":
            result["created_names"] = [item["name"] for item in applied]
            result.pop(self.projection.applied_key)
            result[self.projection.skipped_key] = [item["name"] for item in skipped]
        elif self.family == "campaign_status":
            result.pop(self.projection.applied_key)
            result.pop(self.projection.skipped_key)
        elif self.family == "campaign_shared_set_links":
            result.pop(self.projection.applied_key)
            result[self.projection.skipped_key] = [item["campaign_id"] for item in skipped]
        if self.projection.resource_names:
            result["resource_names"] = list(self.external_refs)
        return result

    def __getitem__(self, key: str) -> Any:
        return self.result()[key]

    def __iter__(self) -> Iterator[str]:
        return iter(self.result())

    def __len__(self) -> int:
        return len(self.result())

    def __eq__(self, other: object) -> bool:
        if isinstance(other, GoogleAdsMutationLedger):
            return (
                self.family,
                self.action,
                self.parents,
                self.projection,
            ) == (other.family, other.action, other.parents, other.projection)
        if isinstance(other, Mapping):
            return self.result() == dict(other)
        return NotImplemented


def build_mutation_ledger(
    *,
    family: str,
    action: str,
    parent_fields: Sequence[Mapping[str, object]],
    skipped_indices: Mapping[int, str],
    submitted: Sequence[tuple[int, Mapping[str, object]]],
    outcomes: Sequence[tuple[MutationEffectOutcome, str | None, str | None, str | None]],
    projection: GoogleAdsMutationProjection,
) -> GoogleAdsMutationLedger:
    """Build and validate a ledger from ordered parents, slots, and reconciled outcomes."""
    if len(submitted) != len(outcomes):
        raise ValueError("Google Ads mutation outcomes must match submitted slots")
    if any(index < 0 or index >= len(parent_fields) for index in skipped_indices):
        raise ValueError("Google Ads skipped outcome references an unknown parent")
    effects_by_parent: dict[int, list[GoogleAdsMutationEffect]] = {}
    for slot, ((parent_index, fields), outcome) in enumerate(zip(submitted, outcomes, strict=True)):
        if parent_index < 0 or parent_index >= len(parent_fields):
            raise ValueError("Google Ads mutation effect references an unknown parent")
        state, external_ref, error_code, message = outcome
        effects_by_parent.setdefault(parent_index, []).append(
            GoogleAdsMutationEffect(
                slot=slot,
                fields=freeze_fields(fields),
                outcome=state,
                external_ref=external_ref,
                error_code=error_code,
                message=message,
            )
        )
    parents: list[GoogleAdsMutationParent] = []
    for index, fields in enumerate(parent_fields):
        effects = tuple(effects_by_parent.get(index, ()))
        if index in skipped_indices:
            if effects:
                raise ValueError("Google Ads mutation parent cannot be skipped and submitted")
            parents.append(
                GoogleAdsMutationParent(
                    identity=freeze_fields(fields),
                    decision="skipped",
                    skip_reason=skipped_indices[index],
                )
            )
        else:
            parents.append(
                GoogleAdsMutationParent(
                    identity=freeze_fields(fields),
                    decision="submit",
                    effects=effects,
                )
            )
    return GoogleAdsMutationLedger(
        family=family,
        action=action,
        parents=tuple(parents),
        projection=projection,
    )


def build_keyword_mutation_ledger(
    *,
    spec: GoogleAdsKeywordMutationSpec,
    action: Literal["add", "remove"],
    parent_fields: Sequence[Mapping[str, object]],
    skipped_indices: Mapping[int, str],
    submitted: Sequence[tuple[int, Mapping[str, object]]],
    outcomes: Sequence[tuple[MutationEffectOutcome, str | None, str | None, str | None]],
) -> GoogleAdsMutationLedger:
    """Build any shared-set, campaign, or ad-group keyword mutation ledger."""
    return build_mutation_ledger(
        family=spec.family,
        action=action,
        parent_fields=parent_fields,
        skipped_indices=skipped_indices,
        submitted=submitted,
        outcomes=outcomes,
        projection=GoogleAdsMutationProjection(
            applied_key="added" if action == "add" else "removed",
            skipped_key="skipped_existing" if action == "add" else "not_found",
            errors_key=spec.errors_key,
            resource_names=(
                spec.add_resource_names if action == "add" else spec.remove_resource_names
            ),
            error_scope=spec.error_scope,
        ),
    )
