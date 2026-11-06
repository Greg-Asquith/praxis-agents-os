# apps/api/integrations/meta_ads/operations/edit_ad.py

"""Rules and the Meta request body for renaming or rescheduling one existing ad.

Creative changes are built in `edit_creative`.
"""

from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from ..tools.schemas.ad_edits import MetaAdsAdEdit, MetaAdsAdSetting
from ..tools.schemas.objects import CLOSED_STATUSES, MetaAdsObject
from .budget_schedules import LOCAL_FORMAT, local_time

# Meta offers an ad its own start and end times only in these campaign objectives.
SCHEDULE_OBJECTIVES = frozenset({"OUTCOME_SALES", "OUTCOME_APP_PROMOTION"})
_TIME_FIELDS = {"start_at": "ad_schedule_start_time", "end_at": "ad_schedule_end_time"}


def ad_values(ad: MetaAdsObject, zone: ZoneInfo) -> dict[str, str | None]:
    """Reads each setting the way an edit names it; a time that isn't set is None."""
    return {
        "name": ad.name,
        "start_at": _local(ad.start_time, zone),
        "end_at": _local(ad.end_time, zone),
        "creative_id": ad.creative_id,
    }


def requested_values(edit: MetaAdsAdEdit) -> dict[MetaAdsAdSetting, str | None]:
    """The values the edit asks for, as `ad_values` reads them; none asks for None."""
    return {
        key: None if (value := getattr(edit, key)) == "none" else value for key in edit.settings
    }


def edit_problems(
    edit: MetaAdsAdEdit,
    ad: MetaAdsObject,
    ad_set: MetaAdsObject,
    *,
    zone: ZoneInfo,
    now: datetime,
) -> list[str]:
    """Lists the Meta rules this edit breaks for the ad as it is now."""
    if ad.status in CLOSED_STATUSES and (set(edit.settings) - {"name"} or edit.creative):
        return ["This ad is archived or deleted, so only its name can change."]
    if edit.start_at is None and edit.end_at is None:
        return []
    if ad_set.objective not in SCHEDULE_OBJECTIVES:
        return [
            "Only ads in sales and app promotion campaigns can have their own start and end "
            "times. Change the ad set's dates instead."
        ]
    after = {**ad_values(ad, zone), **requested_values(edit)}
    start, end = (_parse(after[key], zone) for key in ("start_at", "end_at"))
    problems: list[str] = []
    if edit.start_at not in (None, "none") and start is not None and start < now:
        problems.append(f"Set start_at to {local_time(now, zone)} or later.")
    if edit.end_at not in (None, "none") and end is not None and end <= now:
        problems.append(f"Set end_at after {local_time(now, zone)}.")
    if start is not None and end is not None and end <= start:
        problems.append("Set end_at after start_at.")
    problems.extend(_ad_set_problems(edit, ad_set, start, end, zone))
    return problems


def _ad_set_problems(
    edit: MetaAdsAdEdit,
    ad_set: MetaAdsObject,
    start: datetime | None,
    end: datetime | None,
    zone: ZoneInfo,
) -> list[str]:
    """Keeps the ad's own times inside its ad set's schedule."""
    problems: list[str] = []
    ad_set_start = _aware(ad_set.start_time)
    ad_set_end = _aware(ad_set.end_time)
    if edit.start_at not in (None, "none") and start and ad_set_start and start < ad_set_start:
        problems.append(
            f"Set start_at to {local_time(ad_set_start, zone)} or later, when the ad set starts."
        )
    if edit.end_at not in (None, "none") and end and ad_set_end and end > ad_set_end:
        problems.append(
            f"Set end_at to {local_time(ad_set_end, zone)} or earlier, when the ad set ends."
        )
    return problems


def edit_body(edit: MetaAdsAdEdit, zone: ZoneInfo) -> dict[str, str]:
    """Builds the update Meta receives; an empty time removes the ad's own time."""
    body: dict[str, str] = {}
    if edit.name is not None:
        body["name"] = edit.name
    for key, field in _TIME_FIELDS.items():
        value = getattr(edit, key)
        if value is not None:
            parsed = _parse(None if value == "none" else value, zone)
            body[field] = parsed.isoformat() if parsed is not None else ""
    return body


def _parse(value: str | None, zone: ZoneInfo) -> datetime | None:
    if value is None:
        return None
    return datetime.strptime(value, LOCAL_FORMAT).replace(tzinfo=zone)


def _aware(value: str | None) -> datetime | None:
    if value is None:
        return None
    parsed = datetime.fromisoformat(value)
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)


def _local(value: str | None, zone: ZoneInfo) -> str | None:
    parsed = _aware(value)
    return local_time(parsed, zone) if parsed is not None else None
