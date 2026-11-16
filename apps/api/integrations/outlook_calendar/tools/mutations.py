# apps/api/integrations/outlook_calendar/tools/mutations.py

"""Strict input contracts for Outlook Calendar writes."""

from typing import Annotated, Literal, Self

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, model_validator

from services.integrations.microsoft_graph.time import parse_local_datetime, validate_time_zone

from ..operations.utils import validate_addresses
from ..references import OutlookCalendarReference, OutlookEventReference
from ..settings import outlook_calendar_settings

MAX_ATTENDEES = 100


def _text(value: str) -> str:
    if any(ord(char) < 32 and char not in "\n\r\t" for char in value):
        raise ValueError("Text cannot contain control characters.")
    return value


def _single_line(value: str) -> str:
    if any(ord(char) < 32 for char in value):
        raise ValueError("Enter a single line of text.")
    return value


def _local(field: str):
    def validate(value: str) -> str:
        return parse_local_datetime(value, field=field).isoformat(timespec="seconds")

    return AfterValidator(validate)


def _attendees(value: list[str]) -> list[str]:
    return validate_addresses(value, limit=MAX_ATTENDEES, field="attendees") if value else []


type Subject = Annotated[
    str, Field(strict=True, min_length=1, max_length=255), AfterValidator(_single_line)
]
type Start = Annotated[str, Field(strict=True, max_length=32), _local("start")]
type End = Annotated[str, Field(strict=True, max_length=32), _local("end")]
type TimeZone = Annotated[
    str, Field(strict=True, max_length=64), AfterValidator(validate_time_zone)
]
type Attendees = Annotated[
    list[Annotated[str, Field(strict=True, max_length=320)]],
    Field(strict=True, max_length=MAX_ATTENDEES),
    AfterValidator(_attendees),
]
type EventBody = Annotated[str, Field(strict=True, max_length=50_000), AfterValidator(_text)]
type Location = Annotated[str, Field(strict=True, max_length=255), AfterValidator(_single_line)]
type Comment = Annotated[str, Field(strict=True, max_length=2_000), AfterValidator(_text)]


def _check_times(start: str, end: str, *, is_all_day: bool = False) -> None:
    max_days = outlook_calendar_settings.OUTLOOK_CALENDAR_MAX_RANGE_DAYS
    start_at = parse_local_datetime(start, field="start")
    end_at = parse_local_datetime(end, field="end")
    if end_at <= start_at:
        raise ValueError("end must be after start.")
    if (end_at - start_at).days > max_days:
        raise ValueError(f"An event can last at most {max_days} days.")
    if is_all_day and (
        start_at.time() != end_at.time() or start_at.time().isoformat() != "00:00:00"
    ):
        raise ValueError(
            "An all-day event starts and ends at midnight, such as 2026-11-16T00:00:00."
        )


class _StrictInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class CreateEventInput(_StrictInput):
    subject: Subject
    start: Start
    end: End
    time_zone: TimeZone | None = None
    attendees: Attendees | None = None
    body_html: EventBody = ""
    location: Location = ""
    is_online_meeting: bool = False
    is_all_day: bool = False
    show_as: Literal["free", "tentative", "busy", "oof", "workingElsewhere"] = "busy"
    calendar: OutlookCalendarReference | None = None

    @model_validator(mode="after")
    def validate_times(self) -> Self:
        _check_times(self.start, self.end, is_all_day=self.is_all_day)
        return self


class UpdateEventInput(_StrictInput):
    event: OutlookEventReference
    subject: Subject | None = None
    start: Start | None = None
    end: End | None = None
    time_zone: TimeZone | None = None
    attendees: Attendees | None = None
    body_html: EventBody | None = None
    location: Location | None = None

    @model_validator(mode="after")
    def validate_changes(self) -> Self:
        changes = (self.subject, self.start, self.attendees, self.body_html, self.location)
        if all(value is None for value in changes):
            raise ValueError("Set at least one field to update the event.")
        if (self.start is None) != (self.end is None):
            raise ValueError("Set start and end together to move the event.")
        if self.start is None and self.time_zone is not None:
            raise ValueError("Set start and end with time_zone to move the event.")
        if self.start is not None and self.end is not None:
            _check_times(self.start, self.end)
        return self


class RespondToEventInput(_StrictInput):
    event: OutlookEventReference
    response: Literal["accept", "tentative", "decline"]
    comment: Comment = ""
    send_response: bool = True


class CancelEventInput(_StrictInput):
    event: OutlookEventReference
    comment: Comment = ""
