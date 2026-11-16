# apps/api/integrations/outlook_calendar/operations/utils.py

"""Bounds, time zones, and provenance for Outlook Calendar provider content."""

import re
from collections.abc import Mapping
from typing import Any
from urllib.parse import quote

from core.exceptions.integration import IntegrationValidationError
from services.agents.runtime.untrusted import UntrustedNode
from services.integrations.microsoft_graph.time import graph_local_datetime, validate_time_zone

EVENT_SELECT = (
    "id,subject,start,end,isAllDay,location,organizer,attendees,responseStatus,showAs,"
    "sensitivity,isOnlineMeeting,onlineMeeting,type,isCancelled,webLink"
)
MAX_BODY_CHARS = 20_000
MAX_ATTENDEES = 100
PRIVATE_SUBJECT = "Private appointment"
RESPONSES = frozenset(
    {"none", "organizer", "tentativelyAccepted", "accepted", "declined", "notResponded"}
)
AVAILABILITY = frozenset({"free", "tentative", "busy", "oof", "workingElsewhere", "unknown"})
SENSITIVITY = frozenset({"normal", "personal", "private", "confidential"})
EVENT_TYPES = frozenset({"singleInstance", "occurrence", "exception", "seriesMaster"})
ATTENDEE_TYPES = frozenset({"required", "optional", "resource"})
WEEKDAYS = ("sunday", "monday", "tuesday", "wednesday", "thursday", "friday", "saturday")
_EMAIL = re.compile(r"[^\s@<>\"',;]+@[^\s@<>\"',;]+\.[^\s@<>\"',;]+")
_DATE = re.compile(r"\d{4}-\d{2}-\d{2}")


def text(value: object, limit: int = 500) -> str:
    return value[:limit] if isinstance(value, str) else ""


def choice(value: object, allowed: frozenset[str], default: str) -> str:
    return value if isinstance(value, str) and value in allowed else default


def untrusted(event_id: str, content: str) -> UntrustedNode:
    return UntrustedNode(source_kind="outlook_event", source_ref=event_id, content=content)


def object_payload(value: object, *, operation: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise IntegrationValidationError(
            "Outlook Calendar returned an invalid response",
            provider_key="outlook_calendar",
            operation=operation,
        )
    return value


def calendar_path(calendar_id: str) -> str:
    return f"/me/calendars/{quote(calendar_id, safe='')}"


def event_path(calendar_id: str, event_id: str) -> str:
    return f"{calendar_path(calendar_id)}/events/{quote(event_id, safe='')}"


def zone_header(time_zone: str, *, text_body: bool = False) -> dict[str, str]:
    prefer = f'outlook.timezone="{time_zone}"'
    return {"Prefer": f'{prefer}, outlook.body-content-type="text"' if text_body else prefer}


def effective_time_zone(requested: str | None, metadata: Mapping[str, object]) -> str:
    """Returns the requested zone, else the calendar's mailbox zone, else UTC."""
    if requested is not None:
        return validate_time_zone(requested)
    recorded = metadata.get("time_zone")
    try:
        return validate_time_zone(recorded) if isinstance(recorded, str) else "UTC"
    except ValueError:
        return "UTC"


def validate_addresses(addresses: list[str], *, limit: int, field: str) -> list[str]:
    """Returns trimmed, de-duplicated addresses after checking their form and count."""
    result: list[str] = []
    seen: set[str] = set()
    for value in addresses:
        address = value.strip()
        if not _EMAIL.fullmatch(address) or len(address) > 320:
            raise ValueError(f"{field} must contain email addresses, such as dana@example.com.")
        if address.casefold() not in seen:
            seen.add(address.casefold())
            result.append(address)
    if not 1 <= len(result) <= limit:
        raise ValueError(f"{field} must contain 1 to {limit} email addresses.")
    return result


def local_time(value: object) -> str | None:
    parsed = graph_local_datetime(value)
    return parsed.isoformat(timespec="seconds") if parsed else None


def _person(value: object, event_id: str) -> dict[str, UntrustedNode]:
    email = value.get("emailAddress") if isinstance(value, dict) else None
    return {
        "name": untrusted(event_id, text(email.get("name") if isinstance(email, dict) else None)),
        "address": untrusted(
            event_id, text(email.get("address") if isinstance(email, dict) else None, 320)
        ),
    }


def is_masked(payload: Mapping[str, Any], *, can_view_private: bool) -> bool:
    return not can_view_private and payload.get("sensitivity") in {"private", "confidential"}


def event_summary(
    payload: Mapping[str, Any], *, time_zone: str, can_view_private: bool
) -> dict[str, Any]:
    event_id = text(payload.get("id"), 512)
    masked = is_masked(payload, can_view_private=can_view_private)
    location = payload.get("location")
    attendees = payload.get("attendees")
    response = payload.get("responseStatus")
    meeting = payload.get("onlineMeeting")
    join_url = text(meeting.get("joinUrl"), 2_000) if isinstance(meeting, dict) else ""
    return {
        "event_id": event_id,
        "subject": PRIVATE_SUBJECT if masked else untrusted(event_id, text(payload.get("subject"))),
        "start": local_time(payload.get("start")),
        "end": local_time(payload.get("end")),
        # Graph returns times in the zone named by the Prefer header.
        "time_zone": time_zone,
        "is_all_day": payload.get("isAllDay") is True,
        "location": untrusted(
            event_id,
            "" if masked or not isinstance(location, dict) else text(location.get("displayName")),
        ),
        "organizer": _person(payload.get("organizer"), event_id),
        "attendee_count": len(attendees) if isinstance(attendees, list) else 0,
        "response_status": choice(
            response.get("response") if isinstance(response, dict) else None, RESPONSES, "none"
        ),
        "show_as": choice(payload.get("showAs"), AVAILABILITY, "unknown"),
        "sensitivity": choice(payload.get("sensitivity"), SENSITIVITY, "normal"),
        "is_online_meeting": payload.get("isOnlineMeeting") is True,
        "join_url": untrusted(event_id, join_url) if join_url else None,
        "type": choice(payload.get("type"), EVENT_TYPES, "singleInstance"),
        "is_cancelled": payload.get("isCancelled") is True,
        "web_link": untrusted(event_id, text(payload.get("webLink"), 2_000)),
    }


def event_detail(
    payload: Mapping[str, Any], *, time_zone: str, can_view_private: bool
) -> dict[str, Any]:
    result = event_summary(payload, time_zone=time_zone, can_view_private=can_view_private)
    event_id = result["event_id"]
    masked = is_masked(payload, can_view_private=can_view_private)
    body = payload.get("body")
    content = "" if masked or not isinstance(body, dict) else text(body.get("content"), 10**7)
    attendees = payload.get("attendees")
    result.update(
        body=untrusted(event_id, content[:MAX_BODY_CHARS]),
        truncated=len(content) > MAX_BODY_CHARS,
        attendees=[
            {
                **_person(item, event_id),
                "type": choice(item.get("type"), ATTENDEE_TYPES, "required"),
                "status": choice(
                    item["status"].get("response")
                    if isinstance(item.get("status"), dict)
                    else None,
                    RESPONSES,
                    "none",
                ),
            }
            for item in (attendees if isinstance(attendees, list) else [])[:MAX_ATTENDEES]
            if isinstance(item, dict)
        ],
        series_master_id=text(payload.get("seriesMasterId"), 512) or None,
        ical_uid=untrusted(event_id, text(payload.get("iCalUId"), 1_000)),
        recurrence_summary=recurrence_summary(payload.get("recurrence")),
    )
    return result


def recurrence_summary(value: object) -> str | None:
    """Describes a recurrence from its enumerated pattern fields only."""
    pattern = value.get("pattern") if isinstance(value, dict) else None
    if not isinstance(pattern, dict):
        return None
    interval = pattern.get("interval")
    interval = interval if isinstance(interval, int) and 1 <= interval <= 99 else 1
    unit = {
        "daily": "day",
        "weekly": "week",
        "absoluteMonthly": "month",
        "relativeMonthly": "month",
        "absoluteYearly": "year",
        "relativeYearly": "year",
    }.get(text(pattern.get("type"), 32))
    if unit is None:
        return None
    summary = f"Every {unit}" if interval == 1 else f"Every {interval} {unit}s"
    days = pattern.get("daysOfWeek")
    names = [day.capitalize() for day in WEEKDAYS if isinstance(days, list) and day in days]
    if names:
        summary += f" on {', '.join(names)}"
    occurrence_range = value.get("range") if isinstance(value, dict) else None
    if isinstance(occurrence_range, dict):
        end_date = text(occurrence_range.get("endDate"), 10)
        count = occurrence_range.get("numberOfOccurrences")
        if occurrence_range.get("type") == "endDate" and _DATE.fullmatch(end_date):
            summary += f" until {end_date}"
        elif occurrence_range.get("type") == "numbered" and isinstance(count, int) and count > 0:
            summary += f", {count} times"
    return summary
