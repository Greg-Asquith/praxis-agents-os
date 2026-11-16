# apps/api/integrations/outlook_calendar/operations/list_calendar_view.py

"""Lists event occurrences that overlap a zone-local window in one calendar."""

from datetime import datetime

from services.integrations.microsoft_graph import MicrosoftGraphClient
from services.integrations.microsoft_graph.time import UTC_OFFSET_PADDING, graph_local_datetime

from .utils import EVENT_SELECT, calendar_path, event_summary, text, zone_header

# Events in the offset padding before the window can fill a page before in-window events.
_PADDING_ITEMS = 100


async def list_calendar_view(
    client: MicrosoftGraphClient,
    *,
    calendar_id: str,
    start: datetime,
    end: datetime,
    time_zone: str,
    limit: int,
    can_view_private: bool,
) -> list[dict]:
    if not 1 <= limit <= 100:
        raise ValueError("Outlook Calendar listing requires a limit of 1-100")
    # calendarView reads offset-less bounds as UTC, and Windows zone names have no local
    # offset table, so pad by the widest offsets and filter on the zone-local times Graph returns.
    before, after = UTC_OFFSET_PADDING
    fetch = limit + _PADDING_ITEMS
    events = await client.paginate(
        f"{calendar_path(calendar_id)}/calendarView",
        operation="list_events",
        params={
            "startDateTime": f"{(start - before).isoformat(timespec='seconds')}Z",
            "endDateTime": f"{(end + after).isoformat(timespec='seconds')}Z",
            "$select": EVENT_SELECT,
            "$orderby": "start/dateTime",
            "$top": 100,
        },
        headers=zone_header(time_zone),
        max_items=fetch,
        max_pages=5,
    )
    return [
        event_summary(event, time_zone=time_zone, can_view_private=can_view_private)
        for event in events
        if _overlaps(event, start, end)
    ][:limit]


def _overlaps(event: dict, start: datetime, end: datetime) -> bool:
    event_start = graph_local_datetime(event.get("start"))
    event_end = graph_local_datetime(event.get("end"))
    if event_start is None or event_end is None or not text(event.get("id"), 512):
        return False
    return event_start < end and (event_end > start or event_start == start)
