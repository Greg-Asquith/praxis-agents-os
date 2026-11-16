# apps/api/integrations/outlook_calendar/operations/get_schedule.py

"""Reads free and busy periods for a set of people without event subjects."""

import re
from datetime import datetime

from core.exceptions.integration import IntegrationValidationError
from services.integrations.http import IntegrationRequestPolicy
from services.integrations.microsoft_graph import MicrosoftGraphClient
from services.integrations.microsoft_graph.time import graph_date_time

from .utils import AVAILABILITY, WEEKDAYS, local_time, object_payload, text, zone_header

MAX_BUSY_PERIODS = 200
_VIEW = re.compile(r"[0-4]{0,9000}")
_CLOCK = re.compile(r"\d{2}:\d{2}:\d{2}")
_ZONE_NAME = re.compile(r"[A-Za-z0-9 _/+\-().]{1,64}")


async def get_schedule(
    client: MicrosoftGraphClient,
    *,
    addresses: list[str],
    start: datetime,
    end: datetime,
    time_zone: str,
    interval_minutes: int,
) -> list[dict]:
    payload = object_payload(
        await client.post(
            "/me/calendar/getSchedule",
            operation="get_availability",
            policy=IntegrationRequestPolicy.READ,
            json={
                "schedules": addresses,
                "startTime": graph_date_time(start, time_zone),
                "endTime": graph_date_time(end, time_zone),
                "availabilityViewInterval": interval_minutes,
            },
            headers=zone_header(time_zone),
        ),
        operation="get_availability",
    )
    values = payload.get("value")
    if not isinstance(values, list):
        raise IntegrationValidationError(
            "Outlook Calendar returned an invalid availability response",
            provider_key="outlook_calendar",
            operation="get_availability",
        )
    by_address = {
        text(item.get("scheduleId"), 320).casefold(): item
        for item in values
        if isinstance(item, dict)
    }
    return [_schedule(address, by_address.get(address.casefold())) for address in addresses]


def _schedule(address: str, item: dict | None) -> dict:
    if item is None or "error" in item:
        return {
            "address": address,
            "available": False,
            "availability_view": "",
            "working_hours": None,
            "busy_periods": [],
        }
    view = text(item.get("availabilityView"), 9_000)
    items = item.get("scheduleItems")
    return {
        "address": address,
        "available": True,
        "availability_view": view if _VIEW.fullmatch(view) else "",
        "working_hours": _working_hours(item.get("workingHours")),
        "busy_periods": [
            {"start": start, "end": end, "status": status}
            for period in (items if isinstance(items, list) else [])[:MAX_BUSY_PERIODS]
            if isinstance(period, dict)
            and (status := period.get("status")) in AVAILABILITY - {"free"}
            and (start := local_time(period.get("start")))
            and (end := local_time(period.get("end")))
        ],
    }


def _working_hours(value: object) -> dict | None:
    if not isinstance(value, dict):
        return None
    days = value.get("daysOfWeek")
    start = text(value.get("startTime"), 8)
    end = text(value.get("endTime"), 8)
    zone = value.get("timeZone")
    zone_name = text(zone.get("name"), 64) if isinstance(zone, dict) else ""
    if not _CLOCK.fullmatch(start) or not _CLOCK.fullmatch(end):
        return None
    return {
        "days": [day for day in WEEKDAYS if isinstance(days, list) and day in days],
        "start_time": start,
        "end_time": end,
        "time_zone": zone_name if _ZONE_NAME.fullmatch(zone_name) else None,
    }
