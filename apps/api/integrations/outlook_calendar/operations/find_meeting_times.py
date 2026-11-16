# apps/api/integrations/outlook_calendar/operations/find_meeting_times.py

"""Asks Outlook to suggest meeting times for a set of attendees."""

import re
from datetime import datetime

from services.integrations.http import IntegrationRequestPolicy
from services.integrations.microsoft_graph import MicrosoftGraphClient
from services.integrations.microsoft_graph.time import graph_date_time

from .utils import AVAILABILITY, choice, local_time, object_payload, text, zone_header

_REASON = re.compile(r"[A-Za-z]{1,64}")


async def find_meeting_times(
    client: MicrosoftGraphClient,
    *,
    attendees: list[str],
    start: datetime,
    end: datetime,
    time_zone: str,
    duration_minutes: int,
    max_candidates: int,
    activity_domain: str,
) -> dict:
    payload = object_payload(
        await client.post(
            "/me/findMeetingTimes",
            operation="find_meeting_times",
            policy=IntegrationRequestPolicy.READ,
            json={
                "attendees": [
                    {"type": "required", "emailAddress": {"address": address}}
                    for address in attendees
                ],
                "timeConstraint": {
                    "activityDomain": activity_domain,
                    "timeSlots": [
                        {
                            "start": graph_date_time(start, time_zone),
                            "end": graph_date_time(end, time_zone),
                        }
                    ],
                },
                "meetingDuration": f"PT{duration_minutes}M",
                "maxCandidates": max_candidates,
                "isOrganizerOptional": False,
                "returnSuggestionReasons": False,
            },
            headers=zone_header(time_zone),
        ),
        operation="find_meeting_times",
    )
    requested = {address.casefold(): address for address in attendees}
    suggestions = payload.get("meetingTimeSuggestions")
    reason = text(payload.get("emptySuggestionsReason"), 64)
    return {
        "suggestions": [
            suggestion
            for item in (suggestions if isinstance(suggestions, list) else [])[:max_candidates]
            if isinstance(item, dict) and (suggestion := _suggestion(item, requested))
        ],
        "empty_suggestions_reason": reason if _REASON.fullmatch(reason) else None,
    }


def _suggestion(item: dict, requested: dict[str, str]) -> dict | None:
    slot = item.get("meetingTimeSlot")
    start = local_time(slot.get("start")) if isinstance(slot, dict) else None
    end = local_time(slot.get("end")) if isinstance(slot, dict) else None
    if start is None or end is None:
        return None
    confidence = item.get("confidence")
    attendees = item.get("attendeeAvailability")
    return {
        "start": start,
        "end": end,
        "confidence": (
            float(confidence)
            if isinstance(confidence, int | float) and 0 <= confidence <= 100
            else None
        ),
        "organizer_availability": choice(
            item.get("organizerAvailability"), AVAILABILITY, "unknown"
        ),
        # Only addresses the agent asked about are echoed back.
        "attendee_availability": [
            {
                "address": address,
                "availability": choice(entry.get("availability"), AVAILABILITY, "unknown"),
            }
            for entry in (attendees if isinstance(attendees, list) else [])
            if isinstance(entry, dict)
            and (address := requested.get(_attendee_address(entry).casefold()))
        ],
    }


def _attendee_address(entry: dict) -> str:
    attendee = entry.get("attendee")
    email = attendee.get("emailAddress") if isinstance(attendee, dict) else None
    return text(email.get("address"), 320) if isinstance(email, dict) else ""
