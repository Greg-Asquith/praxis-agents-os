# apps/api/integrations/meta_ads/operations/mutations.py

"""Exact accounting for Meta Ads changes: one parent per object, one or more effects each."""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Literal

from core.exceptions.integration import IntegrationError, IntegrationFailureDisposition
from services.integrations.http import IntegrationRequestPolicy

from ..client import MetaAdsClient
from ..throttle import ensure_account_available
from ..tools.schemas.objects import MetaAdsObject, MetaAdsObjectType
from .list_objects import read_objects_by_id

type MetaAdsEffectOutcome = Literal["applied", "failed", "unverified"]
type MetaAdsParentDecision = Literal["submit", "skipped"]
type FrozenFields = tuple[tuple[str, str], ...]

NOT_DISPATCHED_CODE = "NOT_DISPATCHED"
NOT_DISPATCHED_MESSAGE = "Meta Ads wasn't asked to make this change."
_UNEXPECTED_REPLY = "Meta Ads didn't confirm this change."


def freeze_fields(fields: Mapping[str, object]) -> FrozenFields:
    """Freezes non-empty string fields in insertion order."""
    frozen: list[tuple[str, str]] = []
    for key, value in fields.items():
        if not isinstance(key, str) or not key or not isinstance(value, str) or not value:
            raise ValueError("Meta Ads mutation fields require non-empty strings")
        frozen.append((key, value))
    if not frozen:
        raise ValueError("Meta Ads mutation fields cannot be empty")
    return tuple(frozen)


@dataclass(frozen=True, slots=True)
class MetaAdsMutationEffect:
    """One request sent to Meta for a parent, with what the application can prove about it."""

    fields: FrozenFields
    outcome: MetaAdsEffectOutcome
    external_ref: str | None = None
    error_code: str | None = None
    message: str | None = None

    def __post_init__(self) -> None:
        freeze_fields(dict(self.fields))
        if self.outcome == "applied":
            if not self.external_ref or self.error_code is not None:
                raise ValueError("Applied Meta Ads effects require only an external reference")
        elif self.external_ref is not None or not self.error_code or not self.message:
            raise ValueError("Failed or unverified Meta Ads effects require diagnostics")

    @classmethod
    def from_error(cls, fields: Mapping[str, str], exc: BaseException) -> "MetaAdsMutationEffect":
        """Creates a failed effect for a rejected request, or an unverified one otherwise."""
        disposition = getattr(exc, "failure_disposition", None)
        rejected = disposition in {
            IntegrationFailureDisposition.REJECTED,
            IntegrationFailureDisposition.NOT_DISPATCHED,
        }
        message = exc.user_message if isinstance(exc, IntegrationError) else ""
        return cls(
            fields=freeze_fields(fields),
            outcome="failed" if rejected else "unverified",
            error_code=exc.__class__.__name__[:100],
            message=" ".join(message.split())[:1000] or _UNEXPECTED_REPLY,
        )


@dataclass(frozen=True, slots=True)
class MetaAdsMutationParent:
    """One requested object and the effects dispatched for it."""

    identity: FrozenFields
    decision: MetaAdsParentDecision
    effects: tuple[MetaAdsMutationEffect, ...] = ()
    skip_reason: str | None = None

    def __post_init__(self) -> None:
        freeze_fields(dict(self.identity))
        if self.decision == "skipped":
            if not self.skip_reason or self.effects:
                raise ValueError("Skipped Meta Ads parents require a reason and no effects")
        elif self.skip_reason is not None or not self.effects:
            raise ValueError("Submitted Meta Ads parents require effects and no skip reason")

    @property
    def outcome(self) -> Literal["applied", "skipped", "failed", "unverified"]:
        outcomes = {effect.outcome for effect in self.effects}
        if self.decision == "skipped":
            return "skipped"
        if "unverified" in outcomes:
            return "unverified"
        return "failed" if "failed" in outcomes else "applied"


@dataclass(frozen=True, slots=True)
class MetaAdsMutationLedger:
    """Ordered accounting for one Meta Ads write, generic over object type."""

    action: str
    parents: tuple[MetaAdsMutationParent, ...]

    def __post_init__(self) -> None:
        if not self.action or not self.parents:
            raise ValueError("Meta Ads mutation ledgers require an action and parents")
        identities = [parent.identity for parent in self.parents]
        if len(set(identities)) != len(identities):
            raise ValueError("Meta Ads mutation parents must be unique")

    @property
    def external_refs(self) -> tuple[str, ...]:
        return tuple(
            effect.external_ref
            for parent in self.parents
            for effect in parent.effects
            if effect.outcome == "applied" and effect.external_ref is not None
        )

    @property
    def has_unverified(self) -> bool:
        return any(parent.outcome == "unverified" for parent in self.parents)


def skipped_parent(object_id: str) -> MetaAdsMutationParent:
    """Records an object that already had the requested value, so nothing was sent."""
    return MetaAdsMutationParent(
        identity=(("object_id", object_id),), decision="skipped", skip_reason="already_set"
    )


def submitted_parent(object_id: str, effect: MetaAdsMutationEffect) -> MetaAdsMutationParent:
    return MetaAdsMutationParent(
        identity=(("object_id", object_id),), decision="submit", effects=(effect,)
    )


def not_dispatched_parent(object_id: str, fields: Mapping[str, str]) -> MetaAdsMutationParent:
    """Records a change that wasn't sent because the write stopped before it."""
    return submitted_parent(
        object_id,
        MetaAdsMutationEffect(
            fields=freeze_fields(fields),
            outcome="failed",
            error_code=NOT_DISPATCHED_CODE,
            message=NOT_DISPATCHED_MESSAGE,
        ),
    )


async def send_change(
    client: MetaAdsClient,
    *,
    account_id: str,
    object_id: str,
    data: Mapping[str, str],
    fields: Mapping[str, str],
    operation: str,
) -> MetaAdsMutationEffect | None:
    """Sends one change once, without retry.

    Returns:
        A terminal effect for a rejected or unclear reply, or None when Meta accepted it.
    """
    try:
        ensure_account_available(account_id, operation=operation)
        payload = await client.graph_post(
            object_id,
            data=dict(data),
            operation=operation,
            policy=IntegrationRequestPolicy.MUTATION,
            usage_account_id=account_id,
        )
    except Exception as exc:
        return MetaAdsMutationEffect.from_error(fields, exc)
    if payload != {"success": True}:
        return MetaAdsMutationEffect(
            fields=freeze_fields(fields),
            outcome="unverified",
            error_code="UNEXPECTED_REPLY",
            message=_UNEXPECTED_REPLY,
        )
    return None


async def read_back(
    client: MetaAdsClient,
    *,
    account_id: str,
    currency: str,
    object_ids: Mapping[MetaAdsObjectType, Sequence[str]],
    after: dict[str, MetaAdsObject],
) -> Exception | None:
    """Reads changed objects into `after` as each read returns, so a cancellation keeps them.

    Returns:
        The error that stopped the reads, or None when every read returned.
    """
    try:
        for object_type, ids in object_ids.items():
            if ids:
                after.update(
                    await read_objects_by_id(
                        client,
                        account_id=account_id,
                        object_type=object_type,
                        object_ids=ids,
                        currency=currency,
                    )
                )
    except Exception as exc:
        return exc
    return None
