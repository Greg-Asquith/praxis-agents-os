# apps/api/integrations/outlook_calendar/entity_resolvers/event.py

"""Resolves Outlook event choices within the selected calendars."""

from collections import Counter
from datetime import UTC, datetime, timedelta

from core.exceptions.integration import IntegrationNotFoundError
from services.integrations.entity_references import (
    EntityChoice,
    EntityResolverDefinition,
    EntityResolverPage,
)
from services.integrations.http import IntegrationRequestPolicy

from ..operations.utils import (
    PRIVATE_SUBJECT,
    calendar_path,
    event_path,
    is_masked,
    local_time,
    object_payload,
    text,
    zone_header,
)
from ..references import OutlookEventReference
from ..tools.utils import (
    OUTLOOK_CALENDAR_BINDING,
    calendar_client_for_principal,
    can_view_private,
    entry_time_zone,
)

MAX_CHOICES = 25
SEARCH_DAYS = 30
_SELECT = "id,subject,start,sensitivity,type"


def _subject(entry, event: dict) -> str:
    if is_masked(event, can_view_private=can_view_private(entry)):
        return PRIVATE_SUBJECT
    return text(event.get("subject"))


def _choice(entry, event: dict, time_zone: str) -> EntityChoice:
    start = local_time(event.get("start"))
    when = f"{start.replace('T', ' ')[:16]} {time_zone}" if start else None
    # A change to a series master reaches every occurrence, so the approver must see it.
    series = "Whole series" if event.get("type") == "seriesMaster" else None
    return EntityChoice.from_reference(
        OutlookEventReference(
            calendar_id=entry.external_id,
            event_id=event["id"],
            label=_subject(entry, event) or "(No subject)",
            description=", ".join(part for part in (when, series) if part) or None,
            scope_label=entry.display_name[:500],
        ),
        icon="outlook_calendar",
    )


def _unique_entries(ctx):
    entries = ctx.active_context.compatible_entries(OUTLOOK_CALENDAR_BINDING)
    counts = Counter(entry.external_id for entry in entries)
    return [entry for entry in entries if counts[entry.external_id] == 1]


async def search_events(ctx, search, _dependent_args, page_size, cursor):
    try:
        offset = max(0, min(int(cursor or "0"), MAX_CHOICES))
    except ValueError:
        offset = 0
    needle = search.strip().casefold()
    now = datetime.now(UTC).replace(tzinfo=None, microsecond=0)
    choices = []
    for entry in _unique_entries(ctx):
        if len(choices) >= MAX_CHOICES:
            break
        time_zone = entry_time_zone(entry, None)
        client = await calendar_client_for_principal(
            ctx.db, actor=ctx.actor, workspace=ctx.workspace, entry=entry
        )
        events = await client.paginate(
            f"{calendar_path(entry.external_id)}/calendarView",
            operation="resolve_event",
            params={
                "startDateTime": f"{now.isoformat()}Z",
                "endDateTime": f"{(now + timedelta(days=SEARCH_DAYS)).isoformat()}Z",
                "$select": _SELECT,
                "$orderby": "start/dateTime",
                "$top": 100,
            },
            headers=zone_header(time_zone),
            max_items=200,
            max_pages=2,
        )
        choices.extend(
            _choice(entry, event, time_zone)
            for event in events
            # Matching the shown subject keeps a search from confirming a masked one.
            if text(event.get("id"), 512) and needle in _subject(entry, event).casefold()
        )
    choices = choices[:MAX_CHOICES]
    return EntityResolverPage(
        choices=tuple(choices[offset : offset + page_size]),
        next_cursor=str(offset + page_size) if len(choices) > offset + page_size else None,
    )


async def resolve_events(ctx, values, _dependent_args):
    entries = _unique_entries(ctx)
    choices = []
    for value in values[:MAX_CHOICES]:
        try:
            reference = OutlookEventReference.model_validate(value)
        except ValueError:
            continue
        entry = next((item for item in entries if item.external_id == reference.calendar_id), None)
        if entry is None:
            continue
        time_zone = entry_time_zone(entry, None)
        client = await calendar_client_for_principal(
            ctx.db, actor=ctx.actor, workspace=ctx.workspace, entry=entry
        )
        try:
            event = object_payload(
                await client.get(
                    event_path(reference.calendar_id, reference.event_id),
                    operation="resolve_event",
                    policy=IntegrationRequestPolicy.READ,
                    params={"$select": _SELECT},
                    headers=zone_header(time_zone),
                ),
                operation="resolve_event",
            )
        except IntegrationNotFoundError:
            continue
        choices.append(_choice(entry, {**event, "id": reference.event_id}, time_zone))
    return tuple(choices)


OUTLOOK_EVENT_RESOLVER = EntityResolverDefinition(
    entity_kind="outlook_event",
    reference_type=OutlookEventReference,
    search=search_events,
    resolve=resolve_events,
    max_page_size=20,
    requires_active_context=True,
    provider_key="outlook_calendar",
)
