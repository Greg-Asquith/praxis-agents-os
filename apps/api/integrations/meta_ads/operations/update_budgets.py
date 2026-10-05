# apps/api/integrations/meta_ads/operations/update_budgets.py

"""Change campaign and ad set budgets where they are held, then read each one back."""

import asyncio
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal, localcontext
from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from core.exceptions.integration import IntegrationValidationError
from services.integrations.http import IntegrationRequestPolicy

from ..client import MetaAdsClient
from ..models import MetaAdsObjectBudget
from ..throttle import ensure_account_available
from ..tools.schemas.activities import MetaAdsActivitiesInput
from ..tools.schemas.objects import MetaAdsObject
from .list_activities import list_activities
from .list_objects import read_objects_by_id
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

type MetaAdsBudgetObjectType = Literal["campaign", "adset"]
type MetaAdsBudgetKind = Literal["daily", "lifetime"]

_OPERATION = "update_budgets"
# The client keeps Meta's reason for rejections of operations named validate_*.
_VALIDATE_OPERATION = "validate_update_budgets"
_OBJECT_TYPES: tuple[MetaAdsBudgetObjectType, ...] = ("campaign", "adset")
_CLOSED_STATUSES = frozenset({"ARCHIVED", "DELETED"})
_NOUNS = {"campaign": "campaign", "adset": "ad set"}
_NOT_CONFIRMED = "Meta Ads accepted the change, but the budget still shows a different amount."
_READBACK_FAILED = "Meta Ads accepted the change, but the budget couldn't be read back."
_KIND_CHANGED = (
    "Meta Ads accepted the change, but the budget now shows as a different type, "
    "so its amount isn't shown."
)
_DRY_RUN_UNCONFIRMED = "Meta Ads didn't confirm this change could be made."


@dataclass(frozen=True, slots=True)
class MetaAdsBudgetTarget:
    """One budget to change at the level that holds it, with its live state before the change."""

    object_type: MetaAdsBudgetObjectType
    before: MetaAdsObject
    kind: MetaAdsBudgetKind
    previous_amount: str
    requested_amount: str
    requested_minor: int

    @property
    def object_id(self) -> str:
        return self.before.id

    @property
    def unchanged(self) -> bool:
        return Decimal(self.previous_amount) == Decimal(self.requested_amount)


async def read_budget_objects(
    client: MetaAdsClient,
    *,
    account_id: str,
    currency: str,
    object_ids: Mapping[MetaAdsBudgetObjectType, Sequence[str]],
) -> dict[MetaAdsBudgetObjectType, dict[str, MetaAdsObject]]:
    """Reads each requested campaign and ad set through the account's own edges, in any status."""
    found: dict[MetaAdsBudgetObjectType, dict[str, MetaAdsObject]] = {}
    for object_type in _OBJECT_TYPES:
        ids = object_ids.get(object_type, ())
        found[object_type] = (
            await read_objects_by_id(
                client,
                account_id=account_id,
                object_type=object_type,
                object_ids=ids,
                currency=currency,
            )
            if ids
            else {}
        )
    return found


def lifetime_spent(budget: MetaAdsObjectBudget) -> Decimal | None:
    """Returns what a lifetime budget has spent, or None when it isn't a readable lifetime budget."""
    if budget.kind != "lifetime" or budget.amount is None or budget.remaining is None:
        return None
    with localcontext(prec=1100):
        return Decimal(budget.amount) - Decimal(budget.remaining)


def budget_problem(
    object_type: MetaAdsBudgetObjectType,
    status: str | None,
    budget: MetaAdsObjectBudget | None,
    requested: Decimal,
    *,
    currency: str,
    min_daily_budget: str | None,
) -> str | None:
    """Returns why this object's budget can't be set to the requested amount, or None."""
    noun = _NOUNS[object_type]
    if status in _CLOSED_STATUSES:
        return f"This {noun} is archived or deleted."
    if object_type == "campaign" and budget is None:
        return "This campaign's ad sets hold their own budgets. Change those instead."
    if budget is not None and budget.kind == "campaign":
        return "This ad set spends from its campaign's budget. Change the campaign instead."
    if budget is None or budget.amount is None:
        return f"This {noun}'s budget couldn't be read."
    if (
        budget.kind == "daily"
        and min_daily_budget is not None
        and requested < Decimal(min_daily_budget)
    ):
        return f"The minimum daily budget for this ad account is {min_daily_budget} {currency}."
    spent = lifetime_spent(budget)
    if spent is not None and requested < spent:
        return f"This lifetime budget has already spent {format(spent, 'f')} {currency}."
    return None


def budget_target(
    object_type: MetaAdsBudgetObjectType,
    item: MetaAdsObject,
    requested: Decimal,
    requested_minor: int,
) -> MetaAdsBudgetTarget:
    """Builds the target for an object that `budget_problem` accepted."""
    budget = item.budget
    if budget is None or budget.kind == "campaign" or budget.amount is None:
        raise ValueError("Meta Ads budget target requires a budget held by the object")
    return MetaAdsBudgetTarget(
        object_type=object_type,
        before=item,
        kind=budget.kind,
        previous_amount=budget.amount,
        requested_amount=format(requested, "f"),
        requested_minor=requested_minor,
    )


@dataclass(frozen=True, slots=True)
class MetaAdsRecentBudgetChanges:
    """Budget changes per object in the last hour; counts are lower bounds when incomplete."""

    counts: dict[str, int]
    complete: bool


async def count_recent_budget_changes(
    client: MetaAdsClient,
    *,
    account_id: str,
    timezone_name: str,
    object_ids: Sequence[str],
    now: datetime,
) -> MetaAdsRecentBudgetChanges:
    """Counts each object's budget changes in the hour before `now` from the account history.

    Meta limits how often an ad set budget can change in an hour, so these counts warn
    the approver before a change that Meta might throttle.
    """
    try:
        zone = ZoneInfo(timezone_name)
    except (ValueError, ZoneInfoNotFoundError):
        zone = ZoneInfo("UTC")
    start = now - timedelta(hours=1)
    history = await list_activities(
        client,
        account_id=account_id,
        request=MetaAdsActivitiesInput(
            since=start.astimezone(zone).date(),
            until=now.astimezone(zone).date(),
            object_ids=list(object_ids),
        ),
        timezone_name=zone.key,
    )
    counts = dict.fromkeys(object_ids, 0)
    for event in history.events:
        if (
            event.object_id in counts
            and "budget" in (event.event_type or "")
            and start <= datetime.fromisoformat(event.event_time) <= now
        ):
            counts[event.object_id] += 1
    return MetaAdsRecentBudgetChanges(counts=counts, complete=not history.truncated)


async def validate_budgets(
    client: MetaAdsClient, *, account_id: str, targets: Sequence[MetaAdsBudgetTarget]
) -> dict[str, str]:
    """Asks Meta to check each change without making it.

    Returns:
        Meta's reason for each rejected change, by object ID.
    """
    rejected: dict[str, str] = {}
    for target in targets:
        if target.unchanged:
            continue
        reason = await validate_budget(
            client,
            account_id=account_id,
            object_id=target.object_id,
            kind=target.kind,
            requested_minor=target.requested_minor,
        )
        if reason is not None:
            rejected[target.object_id] = reason
    return rejected


async def validate_budget(
    client: MetaAdsClient,
    *,
    account_id: str,
    object_id: str,
    kind: MetaAdsBudgetKind,
    requested_minor: int,
) -> str | None:
    """Asks Meta to check one change without making it.

    Returns:
        Meta's reason when it rejects the change or doesn't confirm it, otherwise None.
    """
    ensure_account_available(account_id, operation=_OPERATION)
    try:
        payload = await client.graph_post(
            object_id,
            data={
                f"{kind}_budget": str(requested_minor),
                "execution_options": json.dumps(["validate_only"]),
            },
            operation=_VALIDATE_OPERATION,
            # A dry run changes nothing, so retrying it is safe.
            policy=IntegrationRequestPolicy.IDEMPOTENT_WRITE,
            usage_account_id=account_id,
        )
    except IntegrationValidationError as exc:
        return exc.user_message
    return None if payload == {"success": True} else _DRY_RUN_UNCONFIRMED


async def update_budgets(
    client: MetaAdsClient,
    *,
    account_id: str,
    currency: str,
    targets: Sequence[MetaAdsBudgetTarget],
) -> MetaAdsMutationLedger:
    """Sends one budget change per object and verifies each accepted change by reading it back.

    Decreases go first, so spending drops before it rises. Budgets already at the
    requested amount are skipped. A change Meta accepted is applied only when the
    read-back shows the requested amount on the same kind of budget.

    Raises:
        asyncio.CancelledError: With a `ledger` attribute that marks the change in
            flight and any unread accepted change unverified, and later changes as not sent.
    """
    ordered = sorted(
        targets,
        key=lambda target: Decimal(target.requested_amount) > Decimal(target.previous_amount),
    )
    accepted: list[MetaAdsBudgetTarget] = []
    parents: dict[str, MetaAdsMutationParent] = {}
    for index, target in enumerate(ordered):
        if target.unchanged:
            parents[target.object_id] = skipped_parent(target.object_id)
            continue
        try:
            effect = await send_change(
                client,
                account_id=account_id,
                object_id=target.object_id,
                data={f"{target.kind}_budget": str(target.requested_minor)},
                fields=_requested_fields(target),
                operation=_OPERATION,
            )
        except asyncio.CancelledError as exc:
            parents[target.object_id] = submitted_parent(
                target.object_id, MetaAdsMutationEffect.from_error(_requested_fields(target), exc)
            )
            for pending in ordered[index + 1 :]:
                parents[pending.object_id] = not_dispatched_parent(
                    pending.object_id, _requested_fields(pending)
                )
            exc.ledger = _ledger(targets, parents, accepted, {}, exc)
            raise
        if effect is None:
            accepted.append(target)
        else:
            parents[target.object_id] = submitted_parent(target.object_id, effect)

    after: dict[str, MetaAdsObject] = {}
    object_ids = {
        object_type: [target.object_id for target in accepted if target.object_type == object_type]
        for object_type in _OBJECT_TYPES
    }
    try:
        readback_error = await read_back(
            client, account_id=account_id, currency=currency, object_ids=object_ids, after=after
        )
    except asyncio.CancelledError as exc:
        exc.ledger = _ledger(targets, parents, accepted, after, exc)
        raise
    return _ledger(targets, parents, accepted, after, readback_error)


def _ledger(
    targets: Sequence[MetaAdsBudgetTarget],
    parents: dict[str, MetaAdsMutationParent],
    accepted: Sequence[MetaAdsBudgetTarget],
    after: dict[str, MetaAdsObject],
    readback_error: BaseException | None,
) -> MetaAdsMutationLedger:
    for target in accepted:
        parents[target.object_id] = submitted_parent(
            target.object_id,
            _verified_effect(target, after.get(target.object_id), readback_error),
        )
    return MetaAdsMutationLedger(
        action="update_budgets",
        parents=tuple(parents[target.object_id] for target in targets),
    )


def _verified_effect(
    target: MetaAdsBudgetTarget,
    after: MetaAdsObject | None,
    readback_error: BaseException | None,
) -> MetaAdsMutationEffect:
    fields = _requested_fields(target)
    budget = after.budget if after is not None else None
    if budget is not None and budget.amount and budget.kind != target.kind:
        # The amount belongs to another kind of budget, so it isn't recorded as this one.
        return MetaAdsMutationEffect(
            fields=freeze_fields(fields),
            outcome="unverified",
            error_code="BUDGET_NOT_CONFIRMED",
            message=_KIND_CHANGED,
        )
    if budget is not None and budget.amount:
        # Keep what Meta returned even when it disagrees, so the row shows the real amount.
        fields["amount"] = budget.amount
        if Decimal(budget.amount) == Decimal(target.requested_amount):
            return MetaAdsMutationEffect(
                fields=freeze_fields(fields), outcome="applied", external_ref=target.object_id
            )
    readback_failed = after is None and readback_error is not None
    return MetaAdsMutationEffect(
        fields=freeze_fields(fields),
        outcome="unverified",
        error_code="READBACK_FAILED" if readback_failed else "BUDGET_NOT_CONFIRMED",
        message=_READBACK_FAILED if readback_failed else _NOT_CONFIRMED,
    )


def _requested_fields(target: MetaAdsBudgetTarget) -> dict[str, str]:
    return {"budget_kind": target.kind, "requested_amount": target.requested_amount}
