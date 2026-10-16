# apps/api/integrations/meta_ads/operations/edit_impact.py

"""What an edit does beyond the setting itself, as notes the approver reads before approving."""

from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from ..client import MetaAdsClient
from ..money import amount_to_minor, minor_to_amount
from ..tools.schemas.activities import MetaAdsActivitiesInput
from ..tools.schemas.objects import MetaAdsObject
from .list_activities import list_activities
from .list_objects import list_objects

LEARNING_NOTE = "This restarts learning. Results may swing for a few days."
# Meta's guidance is to change bids and budgets no more than 2 to 3 times a day.
DAILY_CHANGE_LIMIT = 3


@dataclass(frozen=True, slots=True)
class MetaAdsRecentChanges:
    """Matching changes per object since a time; counts are lower bounds when incomplete."""

    counts: dict[str, int]
    complete: bool


async def count_recent_changes(
    client: MetaAdsClient,
    *,
    account_id: str,
    timezone_name: str,
    object_ids: Sequence[str],
    since: datetime,
    now: datetime,
    words: tuple[str, ...],
) -> MetaAdsRecentChanges:
    """Counts each object's changes between `since` and `now` from the account history.

    A change counts when its event type contains one of `words`, such as budget or bid.
    Meta limits or advises against frequent changes, so the counts warn the approver.
    """
    try:
        zone = ZoneInfo(timezone_name)
    except (ValueError, ZoneInfoNotFoundError):
        zone = ZoneInfo("UTC")
    history = await list_activities(
        client,
        account_id=account_id,
        request=MetaAdsActivitiesInput(
            since=since.astimezone(zone).date(),
            until=now.astimezone(zone).date(),
            object_ids=list(object_ids),
        ),
        timezone_name=zone.key,
    )
    counts = dict.fromkeys(object_ids, 0)
    for event in history.events:
        if (
            event.object_id in counts
            and any(word in (event.event_type or "") for word in words)
            and since <= datetime.fromisoformat(event.event_time) <= now
        ):
            counts[event.object_id] += 1
    return MetaAdsRecentChanges(counts=counts, complete=not history.truncated)


async def count_ad_bids(
    client: MetaAdsClient, *, account_id: str, currency: str, adset_ids: Sequence[str]
) -> dict[str, int]:
    """Counts, per ad set, the ads with their own bid, which a new ad set bid replaces."""
    counts: Counter[str] = Counter()
    for start in range(0, len(adset_ids), 50):
        ads = await list_objects(
            client,
            account_id=account_id,
            object_type="ad",
            adset_ids=list(adset_ids[start : start + 50]),
            limit=500,
            currency=currency,
        )
        counts.update(ad.adset_id for ad in ads.objects if ad.adset_id and ad.bid_amount)
    return dict(counts)


async def count_active_ad_sets(
    client: MetaAdsClient, *, account_id: str, currency: str, campaign_ids: Sequence[str]
) -> dict[str, int]:
    """Counts each campaign's active ad sets, which share its budget."""
    counts: Counter[str] = Counter()
    for start in range(0, len(campaign_ids), 50):
        ad_sets = await list_objects(
            client,
            account_id=account_id,
            object_type="adset",
            campaign_ids=list(campaign_ids[start : start + 50]),
            statuses=["ACTIVE"],
            limit=500,
            currency=currency,
        )
        counts.update(item.campaign_id for item in ad_sets.objects if item.campaign_id)
    return dict(counts)


@dataclass(frozen=True, slots=True)
class LifetimePace:
    """A lifetime budget's daily spend over its remaining days, before and after a new end."""

    remaining: str
    days_before: int
    days_after: int
    daily_before: str
    daily_after: str


def lifetime_pace(
    ad_set: MetaAdsObject, *, start: date | None, end: date, today: date, currency: str
) -> LifetimePace | None:
    """Spreads what is left of the ad set's own lifetime budget over the days left to run.

    Returns None without an own lifetime budget and a current end date to compare with.
    """
    budget = ad_set.budget
    if budget is None or budget.kind != "lifetime" or ad_set.end_time is None:
        return None
    remaining = budget.remaining or budget.amount
    if remaining is None:
        return None
    first = max(today, start) if start is not None else today
    old_end = datetime.fromisoformat(ad_set.end_time).date()
    days_before = max((old_end - first).days + 1, 1)
    days_after = max((end - first).days + 1, 1)
    return LifetimePace(
        remaining=remaining,
        days_before=days_before,
        days_after=days_after,
        daily_before=_per_day(remaining, days_before, currency),
        daily_after=_per_day(remaining, days_after, currency),
    )


def pace_note(pace: LifetimePace, currency: str) -> str | None:
    difference = pace.days_after - pace.days_before
    if difference == 0:
        return None
    more = "more" if difference > 0 else "fewer"
    days = f"{abs(difference)} {more} {'day' if abs(difference) == 1 else 'days'}"
    return (
        f"The lifetime budget now has {days}, so it "
        f"spends about {pace.daily_after} {currency} a day instead of "
        f"{pace.daily_before} {currency}."
    )


def _per_day(amount: str, days: int, currency: str) -> str:
    minor = Decimal(amount_to_minor(amount, currency)) / days
    return format(minor_to_amount(int(minor.to_integral_value(ROUND_HALF_UP)), currency), "f")


def ad_bids_note(count: int) -> str | None:
    if count == 0:
        return None
    ads = "1 ad" if count == 1 else f"{count} ads"
    return f"This bid replaces the bids set on {ads} in this ad set."


def daily_changes_note(count: int, complete: bool) -> str | None:
    if count < DAILY_CHANGE_LIMIT:
        return None
    times = f"{'at least ' if not complete else ''}{count} times"
    return (
        f"Bids or budgets on this ad set changed {times} today. Meta recommends no more "
        f"than {DAILY_CHANGE_LIMIT}, because each change can unsettle delivery."
    )


def minimum_spend_note(
    minimum: str | None, campaign: MetaAdsObject, active_ad_sets: int, currency: str
) -> str | None:
    """Warns when a minimum spend is more than this ad set's even share of the campaign budget."""
    budget = campaign.budget
    if minimum is None or budget is None or budget.amount is None or active_ad_sets < 1:
        return None
    share = _per_day(budget.amount, active_ad_sets, currency)
    if Decimal(minimum) <= Decimal(share):
        return None
    return (
        f"The minimum is more than this ad set's even share of the campaign budget, about "
        f"{share} {currency}, so other ad sets may get less."
    )
