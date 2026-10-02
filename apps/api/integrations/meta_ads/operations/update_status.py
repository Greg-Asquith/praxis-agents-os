# apps/api/integrations/meta_ads/operations/update_status.py

"""Turn campaigns, ad sets, and ads on or off, then read each one back."""

import asyncio
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal

from services.integrations.http import IntegrationRequestPolicy

from ..client import MetaAdsClient
from ..throttle import ensure_account_available
from ..tools.schemas.objects import MetaAdsObject, MetaAdsObjectType
from .list_objects import read_objects_by_id
from .mutations import (
    NOT_DISPATCHED_CODE,
    NOT_DISPATCHED_MESSAGE,
    MetaAdsMutationEffect,
    MetaAdsMutationLedger,
    MetaAdsMutationParent,
    freeze_fields,
)

type MetaAdsRequestedStatus = Literal["ACTIVE", "PAUSED"]

_OPERATION = "update_status"
_OBJECT_TYPES: tuple[MetaAdsObjectType, ...] = ("campaign", "adset", "ad")
_UNEXPECTED_REPLY = "Meta Ads didn't confirm this change."
_NOT_CONFIRMED = "Meta Ads accepted the change, but the object still shows a different status."
_READBACK_FAILED = "Meta Ads accepted the change, but the object couldn't be read back."


@dataclass(frozen=True, slots=True)
class MetaAdsStatusTarget:
    """One object to change, with its live state and its parents' status before the change."""

    object_type: MetaAdsObjectType
    before: MetaAdsObject
    campaign_status: str | None = None
    adset_status: str | None = None

    @property
    def object_id(self) -> str:
        return self.before.id


async def read_status_targets(
    client: MetaAdsClient,
    *,
    account_id: str,
    currency: str,
    object_ids: dict[MetaAdsObjectType, Sequence[str]],
) -> tuple[list[MetaAdsStatusTarget], list[str]]:
    """Reads each requested object and its parents through the account's own edges.

    Returns:
        The targets in campaign, ad set, then ad order, and the requested IDs the
        account doesn't list.
    """
    ads = await _read(client, account_id, currency, "ad", object_ids.get("ad", ()))
    adset_ids = {*object_ids.get("adset", ()), *(ad.adset_id for ad in ads.values())}
    adsets = await _read(client, account_id, currency, "adset", adset_ids)
    campaign_ids = {
        *object_ids.get("campaign", ()),
        *(item.campaign_id for item in (*adsets.values(), *ads.values())),
    }
    campaigns = await _read(client, account_id, currency, "campaign", campaign_ids)
    found = {"campaign": campaigns, "adset": adsets, "ad": ads}

    targets: list[MetaAdsStatusTarget] = []
    missing: list[str] = []
    for object_type in _OBJECT_TYPES:
        for object_id in sorted(set(object_ids.get(object_type, ()))):
            item = found[object_type].get(object_id)
            if item is None:
                missing.append(object_id)
                continue
            campaign = campaigns.get(item.campaign_id or "")
            adset = adsets.get(item.adset_id or "")
            targets.append(
                MetaAdsStatusTarget(
                    object_type=object_type,
                    before=item,
                    campaign_status=campaign.status if campaign else None,
                    adset_status=adset.status if adset else None,
                )
            )
    return targets, missing


async def update_status(
    client: MetaAdsClient,
    *,
    account_id: str,
    currency: str,
    targets: Sequence[MetaAdsStatusTarget],
    status: MetaAdsRequestedStatus,
) -> tuple[MetaAdsMutationLedger, dict[str, MetaAdsObject | None]]:
    """Sends one status change per object and verifies each accepted change by reading it back.

    Turning off goes campaigns first, so spending stops sooner. Turning on goes ads
    first and campaigns last, so spending starts only once their children are on.
    Objects already at the requested status are skipped. A change Meta accepted is
    applied only when the read-back shows the requested status.

    Returns:
        The ledger, and the state read after the change for skipped objects whose
        campaign or ad set was sent a change, or None where that read failed.

    Raises:
        asyncio.CancelledError: With a `ledger` attribute that marks the change in
            flight and any unread accepted change unverified, and later changes as not sent.
    """
    ordered = sorted(
        targets,
        key=lambda target: _OBJECT_TYPES.index(target.object_type),
        reverse=status == "ACTIVE",
    )
    accepted: list[MetaAdsStatusTarget] = []
    parents: dict[str, MetaAdsMutationParent] = {}
    for index, target in enumerate(ordered):
        if target.before.status == status:
            parents[target.object_id] = _skipped(target)
            continue
        try:
            effect = await _send(client, account_id, target, status)
        except asyncio.CancelledError as exc:
            parents[target.object_id] = _submitted(
                target, MetaAdsMutationEffect.from_error({"requested_status": status}, exc)
            )
            for pending in ordered[index + 1 :]:
                parents[pending.object_id] = _not_dispatched(pending, status)
            exc.ledger = _ledger(targets, parents, accepted, {}, exc, status)
            raise
        if effect is None:
            accepted.append(target)
        else:
            parents[target.object_id] = _submitted(target, effect)

    stale = _skipped_below_changes(targets, parents, accepted)
    try:
        after, readback_error = await _read_back(client, account_id, currency, [*accepted, *stale])
    except asyncio.CancelledError as exc:
        exc.ledger = _ledger(targets, parents, accepted, {}, exc, status)
        raise
    ledger = _ledger(targets, parents, accepted, after, readback_error, status)
    return ledger, {target.object_id: after.get(target.object_id) for target in stale}


def _skipped_below_changes(
    targets: Sequence[MetaAdsStatusTarget],
    parents: dict[str, MetaAdsMutationParent],
    accepted: Sequence[MetaAdsStatusTarget],
) -> list[MetaAdsStatusTarget]:
    """Skipped objects whose delivery status may have moved with a parent's change."""
    sent = {target.object_id for target in accepted} | {
        object_id for object_id, parent in parents.items() if parent.outcome == "unverified"
    }
    return [
        target
        for target in targets
        if target.object_id in parents
        and parents[target.object_id].decision == "skipped"
        and {target.before.campaign_id, target.before.adset_id} & sent
    ]


async def _send(
    client: MetaAdsClient,
    account_id: str,
    target: MetaAdsStatusTarget,
    status: MetaAdsRequestedStatus,
) -> MetaAdsMutationEffect | None:
    """Returns a terminal effect for a rejected or unclear reply, or None when Meta accepted it."""
    fields = {"requested_status": status}
    try:
        ensure_account_available(account_id, operation=_OPERATION)
        payload = await client.graph_post(
            target.object_id,
            data={"status": status},
            operation=_OPERATION,
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


async def _read_back(
    client: MetaAdsClient,
    account_id: str,
    currency: str,
    accepted: Sequence[MetaAdsStatusTarget],
) -> tuple[dict[str, MetaAdsObject], Exception | None]:
    after: dict[str, MetaAdsObject] = {}
    try:
        for object_type in _OBJECT_TYPES:
            ids = [item.object_id for item in accepted if item.object_type == object_type]
            if ids:
                after.update(await _read(client, account_id, currency, object_type, ids))
    except Exception as exc:
        return after, exc
    return after, None


def _ledger(
    targets: Sequence[MetaAdsStatusTarget],
    parents: dict[str, MetaAdsMutationParent],
    accepted: Sequence[MetaAdsStatusTarget],
    after: dict[str, MetaAdsObject],
    readback_error: BaseException | None,
    status: MetaAdsRequestedStatus,
) -> MetaAdsMutationLedger:
    for target in accepted:
        parents[target.object_id] = _submitted(
            target, _verified_effect(after.get(target.object_id), status, readback_error)
        )
    return MetaAdsMutationLedger(
        action="update_status",
        parents=tuple(parents[target.object_id] for target in targets),
    )


def _verified_effect(
    after: MetaAdsObject | None,
    status: MetaAdsRequestedStatus,
    readback_error: BaseException | None,
) -> MetaAdsMutationEffect:
    fields = {"requested_status": status}
    if after is not None:
        # Keep what Meta returned even when it disagrees, so the row shows the real state.
        fields["status"] = after.status
        if after.effective_status:
            fields["effective_status"] = after.effective_status
    if after is not None and after.status == status:
        return MetaAdsMutationEffect(
            fields=freeze_fields(fields), outcome="applied", external_ref=after.id
        )
    readback_failed = after is None and readback_error is not None
    return MetaAdsMutationEffect(
        fields=freeze_fields(fields),
        outcome="unverified",
        error_code="READBACK_FAILED" if readback_failed else "STATUS_NOT_CONFIRMED",
        message=_READBACK_FAILED if readback_failed else _NOT_CONFIRMED,
    )


def _identity(target: MetaAdsStatusTarget) -> dict[str, str]:
    return {"object_id": target.object_id}


def _skipped(target: MetaAdsStatusTarget) -> MetaAdsMutationParent:
    return MetaAdsMutationParent(
        identity=freeze_fields(_identity(target)), decision="skipped", skip_reason="already_set"
    )


def _submitted(target: MetaAdsStatusTarget, effect: MetaAdsMutationEffect) -> MetaAdsMutationParent:
    return MetaAdsMutationParent(
        identity=freeze_fields(_identity(target)), decision="submit", effects=(effect,)
    )


def _not_dispatched(
    target: MetaAdsStatusTarget, status: MetaAdsRequestedStatus
) -> MetaAdsMutationParent:
    return _submitted(
        target,
        MetaAdsMutationEffect(
            fields=freeze_fields({"requested_status": status}),
            outcome="failed",
            error_code=NOT_DISPATCHED_CODE,
            message=NOT_DISPATCHED_MESSAGE,
        ),
    )


async def _read(
    client: MetaAdsClient,
    account_id: str,
    currency: str,
    object_type: MetaAdsObjectType,
    ids: Sequence[str | None] | set[str | None],
) -> dict[str, MetaAdsObject]:
    wanted = [item for item in ids if item]
    if not wanted:
        return {}
    return await read_objects_by_id(
        client, account_id=account_id, object_type=object_type, object_ids=wanted, currency=currency
    )
