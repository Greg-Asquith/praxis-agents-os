# apps/api/integrations/outlook_calendar/entity_resolvers/calendar.py

"""Resolves Outlook calendar choices from the active context without provider I/O."""

from services.integrations.entity_references import (
    EntityChoice,
    EntityResolverDefinition,
    EntityResolverPage,
)

from ..references import OutlookCalendarReference
from ..tools.utils import OUTLOOK_CALENDAR_BINDING, calendar_reference


def _choices(ctx) -> list[EntityChoice]:
    return [
        EntityChoice.from_reference(calendar_reference(entry), icon="outlook_calendar")
        for entry in ctx.active_context.compatible_entries(OUTLOOK_CALENDAR_BINDING)
        if entry.write_allowed
    ]


async def search_calendars(ctx, search, _dependent_args, page_size, cursor):
    try:
        offset = max(0, int(cursor or "0"))
    except ValueError:
        offset = 0
    needle = search.strip().casefold()
    choices = [choice for choice in _choices(ctx) if needle in choice.label.casefold()]
    return EntityResolverPage(
        choices=tuple(choices[offset : offset + page_size]),
        next_cursor=str(offset + page_size) if len(choices) > offset + page_size else None,
    )


async def resolve_calendars(ctx, values, _dependent_args):
    by_id = {choice.value["calendar_id"]: choice for choice in _choices(ctx)}
    choices = []
    for value in values:
        try:
            reference = OutlookCalendarReference.model_validate(value)
        except ValueError:
            continue
        if reference.calendar_id in by_id:
            choices.append(by_id[reference.calendar_id])
    return tuple(choices)


OUTLOOK_CALENDAR_RESOLVER = EntityResolverDefinition(
    entity_kind="outlook_calendar",
    reference_type=OutlookCalendarReference,
    search=search_calendars,
    resolve=resolve_calendars,
    max_page_size=20,
    requires_active_context=True,
    provider_key="outlook_calendar",
)
