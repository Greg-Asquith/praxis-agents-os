# apps/api/integrations/meta_ads/operations/budget_schedules.py

"""Add high-demand periods that raise a daily budget, then read each one back."""

import asyncio
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Literal
from zoneinfo import ZoneInfo

from services.integrations.http import IntegrationRequestPolicy

from ..client import MetaAdsClient, ad_account_path
from ..money import amount_to_minor, minor_to_amount
from ..throttle import ensure_account_available
from ..tools.schemas.budget_schedules import MAX_PERIODS, MetaAdsBudgetPeriod
from ..tools.schemas.objects import CLOSED_STATUSES, MetaAdsObject
from .mutations import (
    NOT_DISPATCHED_CODE,
    NOT_DISPATCHED_MESSAGE,
    MetaAdsMutationEffect,
    MetaAdsMutationLedger,
    MetaAdsMutationParent,
    freeze_fields,
)
from .values import invalid_response, numeric_value

type MetaAdsScheduleObjectType = Literal["campaign", "adset"]

_OPERATION = "schedule_budget_increases"
_READ_OPERATION = "read_budget_schedules"
_CAPABILITY = "CAN_USE_BUDGET_SCHEDULING_API"
_PERIOD_FIELDS = "id,budget_value,budget_value_type,time_start,time_end"
LOCAL_FORMAT = "%Y-%m-%dT%H:%M"
_MIN_LENGTH = timedelta(hours=3)
# During a period the daily budget plus the increase can be at most this multiple of it.
_MAX_MULTIPLE = 8
_NOUNS = {"campaign": "campaign", "adset": "ad set"}
_NOT_CONFIRMED = "Meta Ads accepted this period, but it reads back with different times or amount."
_NOT_FOUND = "Meta Ads accepted this period, but it isn't in the campaign's or ad set's schedule."
_READBACK_FAILED = "Meta Ads accepted this period, but the schedule couldn't be read back."
_UNEXPECTED_REPLY = "Meta Ads didn't confirm this period."


@dataclass(frozen=True, slots=True)
class MetaAdsExistingPeriod:
    """One high-demand period Meta already holds for the campaign or ad set."""

    id: str
    start: datetime
    end: datetime
    # ABSOLUTE in minor units, or MULTIPLIER as Meta stores it.
    value_type: str
    value: int


@dataclass(frozen=True, slots=True)
class MetaAdsPlannedPeriod:
    """One new period, numbered from 1 in the order requested, with the increase to send."""

    number: int
    start: datetime
    end: datetime
    increase_amount: str
    increase_minor: int
    increase_percent: int | None


@dataclass(frozen=True, slots=True)
class MetaAdsPeriodReview:
    """One requested period, ready to send or with the reason it can't be."""

    request: MetaAdsBudgetPeriod
    planned: MetaAdsPlannedPeriod | None
    problem: str | None


def schedule_problem(object_type: MetaAdsScheduleObjectType, item: MetaAdsObject) -> str | None:
    """Returns why this object can't take budget increases, or None."""
    noun = _NOUNS[object_type]
    budget = item.budget
    if item.status in CLOSED_STATUSES:
        return f"This {noun} is archived or deleted."
    if object_type == "campaign" and budget is None:
        return "This campaign's ad sets hold their own budgets. Schedule increases on them instead."
    if budget is not None and budget.kind == "campaign":
        return "This ad set spends from its campaign's budget. Schedule the increase there instead."
    if budget is not None and budget.kind == "lifetime":
        return f"Budget increases need a daily budget, and this {noun} has a lifetime budget."
    if budget is None or budget.amount is None:
        return f"This {noun}'s budget couldn't be read."
    return None


async def can_schedule_budgets(client: MetaAdsClient, *, account_id: str) -> bool:
    """Checks whether Meta lets this ad account schedule budget increases through the API."""
    ensure_account_available(account_id, operation=_READ_OPERATION)
    raw = await client.graph_get(
        ad_account_path(account_id),
        params={"fields": "capabilities"},
        operation=_READ_OPERATION,
        policy=IntegrationRequestPolicy.READ,
        usage_account_id=account_id,
    )
    capabilities = raw.get("capabilities")
    return isinstance(capabilities, list) and _CAPABILITY in capabilities


async def read_periods(
    client: MetaAdsClient, *, account_id: str, object_id: str
) -> list[MetaAdsExistingPeriod]:
    """Reads every high-demand period the campaign or ad set holds."""
    ensure_account_available(account_id, operation=_READ_OPERATION)
    rows, _truncated = await client.graph_get_paged(
        f"{object_id}/budget_schedules",
        params={"fields": _PERIOD_FIELDS, "limit": str(MAX_PERIODS)},
        operation=_READ_OPERATION,
        policy=IntegrationRequestPolicy.READ,
        max_pages=2,
    )
    return [_existing(row) for row in rows]


def _existing(row: Mapping[str, Any]) -> MetaAdsExistingPeriod:
    period_id, value_type = row.get("id"), row.get("budget_value_type")
    if not isinstance(period_id, str) or not period_id.isdigit():
        raise invalid_response("Meta Ads returned a period without an ID.", operation=_OPERATION)
    value = numeric_value(row.get("budget_value"), count=True, operation=_OPERATION)
    if value is None or not isinstance(value_type, str):
        raise invalid_response("Meta Ads returned a period without a value.", operation=_OPERATION)
    return MetaAdsExistingPeriod(
        id=period_id,
        start=_meta_time(row.get("time_start")),
        end=_meta_time(row.get("time_end")),
        value_type=value_type,
        value=int(value),
    )


def _meta_time(value: Any) -> datetime:
    try:
        if isinstance(value, int) and not isinstance(value, bool):
            return datetime.fromtimestamp(value, UTC)
        if isinstance(value, str):
            parsed = datetime.fromisoformat(value)
            if parsed.tzinfo is not None:
                return parsed
    except (ValueError, OverflowError):
        pass
    raise invalid_response("Meta Ads returned a period without valid times.", operation=_OPERATION)


def local_time(value: datetime, zone: ZoneInfo) -> str:
    """Formats a time as YYYY-MM-DDTHH:MM in the ad account's time zone."""
    return value.astimezone(zone).strftime(LOCAL_FORMAT)


def review_periods(
    periods: Sequence[MetaAdsBudgetPeriod],
    existing: Sequence[MetaAdsExistingPeriod],
    *,
    daily_budget: str,
    currency: str,
    zone: ZoneInfo,
    now: datetime,
) -> list[MetaAdsPeriodReview]:
    """Applies Meta's period rules to each requested period, in the order requested.

    An increase given as a percentage becomes a fixed amount of today's daily budget,
    rounded down to whole minor units.
    """
    daily_minor = amount_to_minor(daily_budget, currency)
    taken = [(item.start, item.end) for item in existing]
    reviews: list[MetaAdsPeriodReview] = []
    for number, period in enumerate(periods, start=1):
        planned, problem = _plan(
            number, period, daily_minor=daily_minor, currency=currency, zone=zone, now=now
        )
        if planned is not None and problem is None:
            problem = _overlap_problem(planned, taken, zone)
            taken.append((planned.start, planned.end))
        reviews.append(MetaAdsPeriodReview(request=period, planned=planned, problem=problem))
    return reviews


def _plan(
    number: int,
    period: MetaAdsBudgetPeriod,
    *,
    daily_minor: int,
    currency: str,
    zone: ZoneInfo,
    now: datetime,
) -> tuple[MetaAdsPlannedPeriod | None, str | None]:
    try:
        start = datetime.strptime(period.start, LOCAL_FORMAT).replace(tzinfo=zone)
        end = datetime.strptime(period.end, LOCAL_FORMAT).replace(tzinfo=zone)
    except ValueError:
        return None, "Use a real date and time for the start and end."
    if start <= now:
        return None, "Start this period in the future."
    if end - start < _MIN_LENGTH:
        return None, "Make this period at least 3 hours long."
    if period.increase_percent is not None:
        increase_minor = daily_minor * period.increase_percent // 100
    else:
        try:
            increase_minor = amount_to_minor(period.increase_amount or "", currency)
        except ValueError:
            return None, f"Use whole {currency} amounts for this increase."
    if increase_minor < 1:
        return None, "This increase is too small to change the budget."
    planned = MetaAdsPlannedPeriod(
        number=number,
        start=start,
        end=end,
        increase_amount=format(minor_to_amount(increase_minor, currency), "f"),
        increase_minor=increase_minor,
        increase_percent=period.increase_percent,
    )
    if increase_minor > daily_minor * (_MAX_MULTIPLE - 1):
        most = format(minor_to_amount(daily_minor * (_MAX_MULTIPLE - 1), currency), "f")
        return planned, (
            f"Meta allows a budget of at most {_MAX_MULTIPLE} times the daily budget, so the "
            f"increase can be at most {most} {currency}."
        )
    return planned, None


def _overlap_problem(
    planned: MetaAdsPlannedPeriod,
    taken: Sequence[tuple[datetime, datetime]],
    zone: ZoneInfo,
) -> str | None:
    for start, end in taken:
        if planned.start < end and start < planned.end:
            return (
                f"This period overlaps the one from {local_time(start, zone)} "
                f"to {local_time(end, zone)}."
            )
    return None


def count_problem(existing: int, new: int) -> str | None:
    """Returns why the object can't hold this many periods, or None."""
    if existing + new > MAX_PERIODS:
        return (
            f"Meta allows {MAX_PERIODS} periods on a campaign or ad set, and this one already "
            f"has {existing}."
        )
    return None


async def add_periods(
    client: MetaAdsClient,
    *,
    account_id: str,
    object_id: str,
    periods: Sequence[MetaAdsPlannedPeriod],
) -> MetaAdsMutationLedger:
    """Sends each period once, in time order, and verifies each accepted one by reading it back.

    A period is applied only when the read-back shows the same times and amount under the
    ID Meta returned.

    Raises:
        asyncio.CancelledError: With a `ledger` attribute that marks the period in flight
            unverified, any unread accepted period unverified, and later periods as not sent.
    """
    ordered = sorted(periods, key=lambda period: period.start)
    accepted: dict[int, str] = {}
    parents: dict[int, MetaAdsMutationParent] = {}
    for index, period in enumerate(ordered):
        try:
            outcome = await _send_period(
                client, account_id=account_id, object_id=object_id, period=period
            )
        except asyncio.CancelledError as exc:
            parents[period.number] = _parent(
                period, MetaAdsMutationEffect.from_error(_fields(period), exc)
            )
            for pending in ordered[index + 1 :]:
                parents[pending.number] = _parent(pending, _not_sent(pending))
            exc.ledger = _ledger(periods, parents, accepted, None, exc)
            raise
        if isinstance(outcome, str):
            accepted[period.number] = outcome
        else:
            parents[period.number] = _parent(period, outcome)
    if not accepted:
        return _ledger(periods, parents, accepted, None, None)
    try:
        after = await read_periods(client, account_id=account_id, object_id=object_id)
    except asyncio.CancelledError as exc:
        exc.ledger = _ledger(periods, parents, accepted, None, exc)
        raise
    except Exception as exc:
        return _ledger(periods, parents, accepted, None, exc)
    return _ledger(periods, parents, accepted, after, None)


async def _send_period(
    client: MetaAdsClient, *, account_id: str, object_id: str, period: MetaAdsPlannedPeriod
) -> str | MetaAdsMutationEffect:
    """Returns the new period's ID, or a terminal effect for a rejected or unclear reply."""
    try:
        ensure_account_available(account_id, operation=_OPERATION)
        payload = await client.graph_post(
            f"{object_id}/budget_schedules",
            data={
                "budget_value": str(period.increase_minor),
                "budget_value_type": "ABSOLUTE",
                "time_start": str(int(period.start.timestamp())),
                "time_end": str(int(period.end.timestamp())),
            },
            operation=_OPERATION,
            # Each post adds a period, so an unclear reply is never sent again.
            policy=IntegrationRequestPolicy.MUTATION,
            usage_account_id=account_id,
        )
    except Exception as exc:
        return MetaAdsMutationEffect.from_error(_fields(period), exc)
    period_id = payload.get("id")
    if isinstance(period_id, str) and period_id.isdigit():
        return period_id
    return MetaAdsMutationEffect(
        fields=freeze_fields(_fields(period)),
        outcome="unverified",
        error_code="UNEXPECTED_REPLY",
        message=_UNEXPECTED_REPLY,
    )


def _ledger(
    periods: Sequence[MetaAdsPlannedPeriod],
    parents: dict[int, MetaAdsMutationParent],
    accepted: Mapping[int, str],
    after: Sequence[MetaAdsExistingPeriod] | None,
    readback_error: BaseException | None,
) -> MetaAdsMutationLedger:
    found = {item.id: item for item in after or ()}
    for period in periods:
        if (period_id := accepted.get(period.number)) is not None:
            parents[period.number] = _parent(
                period, _verified_effect(period, period_id, found.get(period_id), readback_error)
            )
    return MetaAdsMutationLedger(
        action=_OPERATION, parents=tuple(parents[period.number] for period in periods)
    )


def _verified_effect(
    period: MetaAdsPlannedPeriod,
    period_id: str,
    after: MetaAdsExistingPeriod | None,
    readback_error: BaseException | None,
) -> MetaAdsMutationEffect:
    fields = {**_fields(period), "period_id": period_id}
    if after is not None and (after.start, after.end, after.value_type, after.value) == (
        period.start,
        period.end,
        "ABSOLUTE",
        period.increase_minor,
    ):
        return MetaAdsMutationEffect(
            fields=freeze_fields(fields), outcome="applied", external_ref=period_id
        )
    if after is None and readback_error is not None:
        code, message = "READBACK_FAILED", _READBACK_FAILED
    else:
        code, message = "PERIOD_NOT_CONFIRMED", _NOT_CONFIRMED if after else _NOT_FOUND
    return MetaAdsMutationEffect(
        fields=freeze_fields(fields), outcome="unverified", error_code=code, message=message
    )


def _parent(period: MetaAdsPlannedPeriod, effect: MetaAdsMutationEffect) -> MetaAdsMutationParent:
    return MetaAdsMutationParent(
        identity=(("period", str(period.number)),), decision="submit", effects=(effect,)
    )


def _not_sent(period: MetaAdsPlannedPeriod) -> MetaAdsMutationEffect:
    return MetaAdsMutationEffect(
        fields=freeze_fields(_fields(period)),
        outcome="failed",
        error_code=NOT_DISPATCHED_CODE,
        message=NOT_DISPATCHED_MESSAGE,
    )


def _fields(period: MetaAdsPlannedPeriod) -> dict[str, str]:
    return {
        "time_start": period.start.isoformat(),
        "time_end": period.end.isoformat(),
        "increase_minor": str(period.increase_minor),
    }
