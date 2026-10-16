# apps/api/integrations/meta_ads/operations/update_fields.py

"""Change settings on existing campaigns or ad sets, one object at a time, then read each back."""

import asyncio
import json
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Literal

from core.exceptions.integration import IntegrationValidationError
from services.audit_events import IntegrationOperationCheckpoint
from services.integrations.http import IntegrationRequestPolicy
from services.integrations.operations import checkpoint_integration_operation

from ..client import MetaAdsClient
from ..throttle import ensure_account_available
from ..tools.schemas.objects import MetaAdsObject
from .mutations import (
    MetaAdsMutationEffect,
    MetaAdsMutationLedger,
    MetaAdsMutationParent,
    freeze_fields,
    not_dispatched_parent,
    read_back,
    send_change,
    skipped_parent,
    submitted_parent,
)

type MetaAdsEditObjectType = Literal["campaign", "adset"]
# Each setting's value as the edit tools name it; None means not set.
type SettingValues = Mapping[str, str | None]

STALE_CODE = "CHANGED_SINCE_APPROVAL"
_NOT_CONFIRMED = "Meta Ads accepted the change, but {settings} still shows a different value."
_READBACK_FAILED = "Meta Ads accepted the change, but it couldn't be read back."
_DRY_RUN_UNCONFIRMED = "Meta Ads didn't confirm this change could be made."


@dataclass(frozen=True, slots=True)
class FieldChange:
    """One object's settings: their values before, the requested values, and Meta's body."""

    object_type: MetaAdsEditObjectType
    before: MetaAdsObject
    before_values: SettingValues
    requested: SettingValues
    body: Mapping[str, str]
    # Why the change mustn't be sent, such as an object that changed after approval.
    refused: str | None = None

    @property
    def object_id(self) -> str:
        return self.before.id

    @property
    def unchanged(self) -> bool:
        return all(
            same_value(self.before_values.get(key), value) for key, value in self.requested.items()
        )


def same_value(left: str | None, right: str | None) -> bool:
    """Compares setting values, treating amounts such as 25 and 25.00 as equal."""
    if left is None or right is None:
        return left is right
    try:
        return Decimal(left) == Decimal(right)
    except InvalidOperation:
        return left == right


async def validate_fields(
    client: MetaAdsClient,
    *,
    account_id: str,
    object_id: str,
    body: Mapping[str, str],
    operation: str,
) -> str | None:
    """Asks Meta to check one change without making it.

    Returns:
        Meta's reason when it rejects the change or doesn't confirm it, otherwise None.
    """
    ensure_account_available(account_id, operation=operation)
    try:
        payload = await client.graph_post(
            object_id,
            data={**body, "execution_options": json.dumps(["validate_only"])},
            # The client keeps Meta's reason for rejections of operations named validate_*.
            operation=f"validate_{operation}",
            # A dry run changes nothing, so retrying it is safe.
            policy=IntegrationRequestPolicy.IDEMPOTENT_WRITE,
            usage_account_id=account_id,
        )
    except IntegrationValidationError as exc:
        return exc.user_message
    return None if payload == {"success": True} else _DRY_RUN_UNCONFIRMED


async def update_fields(
    client: MetaAdsClient,
    *,
    account_id: str,
    currency: str,
    changes: Sequence[FieldChange],
    values: Callable[[MetaAdsObject], SettingValues],
    action: str,
    group_key: str,
    operation: str,
) -> MetaAdsMutationLedger:
    """Sends each change once, in order, then verifies every accepted one by reading it back.

    A checkpoint marks each object before its change is sent, so recovery knows which
    objects might have changed. `values` reads an object's settings for the comparison.
    Objects already at the requested values are skipped; refused ones are never sent.

    Raises:
        asyncio.CancelledError: With a `ledger` attribute that marks the change in flight
            and any unread accepted change unverified, and later changes as not sent.
    """
    accepted: list[FieldChange] = []
    parents: dict[str, MetaAdsMutationParent] = {}
    for index, change in enumerate(changes):
        if change.refused is not None:
            parents[change.object_id] = submitted_parent(change.object_id, _refused_effect(change))
            continue
        if change.unchanged:
            parents[change.object_id] = skipped_parent(change.object_id)
            continue
        try:
            await checkpoint_integration_operation(
                IntegrationOperationCheckpoint(
                    group_key=group_key,
                    intent_index=index,
                    references={"object_id": change.object_id},
                )
            )
            effect = await send_change(
                client,
                account_id=account_id,
                object_id=change.object_id,
                data=change.body,
                fields=_requested_fields(change),
                operation=operation,
            )
        except asyncio.CancelledError as exc:
            parents[change.object_id] = submitted_parent(
                change.object_id,
                MetaAdsMutationEffect.from_error(_requested_fields(change), exc),
            )
            for pending in changes[index + 1 :]:
                parents[pending.object_id] = not_dispatched_parent(
                    pending.object_id, _requested_fields(pending)
                )
            exc.ledger = _ledger(action, changes, parents, accepted, {}, values)
            raise
        if effect is None:
            accepted.append(change)
        else:
            parents[change.object_id] = submitted_parent(change.object_id, effect)

    after: dict[str, MetaAdsObject] = {}
    object_ids: dict[MetaAdsEditObjectType, list[str]] = {"campaign": [], "adset": []}
    for change in accepted:
        object_ids[change.object_type].append(change.object_id)
    try:
        # A failed read leaves the objects it didn't return unverified.
        await read_back(
            client, account_id=account_id, currency=currency, object_ids=object_ids, after=after
        )
    except asyncio.CancelledError as exc:
        exc.ledger = _ledger(action, changes, parents, accepted, after, values)
        raise
    return _ledger(action, changes, parents, accepted, after, values)


def _ledger(
    action: str,
    changes: Sequence[FieldChange],
    parents: dict[str, MetaAdsMutationParent],
    accepted: Sequence[FieldChange],
    after: Mapping[str, MetaAdsObject],
    values: Callable[[MetaAdsObject], SettingValues],
) -> MetaAdsMutationLedger:
    for change in accepted:
        read = after.get(change.object_id)
        parents[change.object_id] = submitted_parent(
            change.object_id,
            _verified_effect(change, values(read) if read is not None else None),
        )
    return MetaAdsMutationLedger(
        action=action, parents=tuple(parents[change.object_id] for change in changes)
    )


def _verified_effect(change: FieldChange, read: SettingValues | None) -> MetaAdsMutationEffect:
    fields = _requested_fields(change)
    if read is None:
        return MetaAdsMutationEffect(
            fields=freeze_fields(fields),
            outcome="unverified",
            error_code="READBACK_FAILED",
            message=_READBACK_FAILED,
        )
    # Keep what Meta returned even when it disagrees, so the row shows the real value.
    fields.update({f"after.{key}": read.get(key) or "none" for key in change.requested})
    different = [
        key for key, value in change.requested.items() if not same_value(read.get(key), value)
    ]
    if not different:
        return MetaAdsMutationEffect(
            fields=freeze_fields(fields), outcome="applied", external_ref=change.object_id
        )
    return MetaAdsMutationEffect(
        fields=freeze_fields(fields),
        outcome="failed",
        error_code="SETTING_NOT_CONFIRMED",
        message=_NOT_CONFIRMED.format(settings=", ".join(different).replace("_", " ")),
    )


def _refused_effect(change: FieldChange) -> MetaAdsMutationEffect:
    return MetaAdsMutationEffect(
        fields=freeze_fields(_requested_fields(change)),
        outcome="failed",
        error_code=STALE_CODE,
        message=change.refused,
    )


def _requested_fields(change: FieldChange) -> dict[str, str]:
    return {"settings": ",".join(change.requested)}
