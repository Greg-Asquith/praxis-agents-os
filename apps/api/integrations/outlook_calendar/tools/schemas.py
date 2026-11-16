# apps/api/integrations/outlook_calendar/tools/schemas.py

"""Typed Outlook Calendar tool result contracts."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from services.agents.runtime.untrusted import UntrustedNode
from services.integrations.context.results import IntegrationFanOutEntry, IntegrationFanOutOutput

from ..references import OutlookEventReference

type UntrustedText = str | UntrustedNode
type Availability = Literal["free", "tentative", "busy", "oof", "workingElsewhere", "unknown"]
type Response = Literal[
    "none", "organizer", "tentativelyAccepted", "accepted", "declined", "notResponded"
]
type Weekday = Literal["sunday", "monday", "tuesday", "wednesday", "thursday", "friday", "saturday"]


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Person(_StrictModel):
    name: UntrustedText
    address: UntrustedText


class Event(_StrictModel):
    reference: OutlookEventReference
    subject: UntrustedText
    start: str | None
    end: str | None
    time_zone: str
    is_all_day: bool
    location: UntrustedText
    organizer: Person
    attendee_count: int = Field(ge=0)
    response_status: Response
    show_as: Availability
    sensitivity: Literal["normal", "personal", "private", "confidential"]
    is_online_meeting: bool
    join_url: UntrustedText | None
    type: Literal["singleInstance", "occurrence", "exception", "seriesMaster"]
    is_cancelled: bool
    web_link: UntrustedText


class Attendee(Person):
    type: Literal["required", "optional", "resource"]
    status: Response


class EventDetail(Event):
    body: UntrustedText
    truncated: bool
    attendees: list[Attendee] = Field(max_length=100)
    series_master_id: str | None
    ical_uid: UntrustedText
    recurrence_summary: str | None


class EventsData(_StrictModel):
    events: list[Event] = Field(max_length=100)
    count: int = Field(ge=0, le=100)
    time_zone: str


class WorkingHours(_StrictModel):
    days: list[Weekday] = Field(max_length=7)
    start_time: str
    end_time: str
    time_zone: str | None


class BusyPeriod(_StrictModel):
    start: str
    end: str
    status: Availability


class Schedule(_StrictModel):
    address: str
    available: bool
    availability_view: str
    working_hours: WorkingHours | None
    busy_periods: list[BusyPeriod] = Field(max_length=200)


class AvailabilityData(_StrictModel):
    schedules: list[Schedule] = Field(max_length=20)
    interval_minutes: int
    time_zone: str


class AttendeeAvailability(_StrictModel):
    address: str
    availability: Availability


class Suggestion(_StrictModel):
    start: str
    end: str
    confidence: float | None
    organizer_availability: Availability
    attendee_availability: list[AttendeeAvailability] = Field(max_length=20)


class MeetingTimesData(_StrictModel):
    suggestions: list[Suggestion] = Field(max_length=10)
    empty_suggestions_reason: str | None
    time_zone: str


class Contact(Person):
    job_title: UntrustedText
    department: UntrustedText


class PeopleData(_StrictModel):
    people: list[Contact] = Field(max_length=25)
    count: int = Field(ge=0, le=25)


class EventsEntry(IntegrationFanOutEntry):
    data: EventsData | None = None


class EventEntry(IntegrationFanOutEntry):
    data: EventDetail | None = None


class AvailabilityEntry(IntegrationFanOutEntry):
    data: AvailabilityData | None = None


class MeetingTimesEntry(IntegrationFanOutEntry):
    data: MeetingTimesData | None = None


class WriteData(_StrictModel):
    event: OutlookEventReference | None
    action: str
    event_type: Literal["singleInstance", "occurrence", "exception", "seriesMaster"] | None
    web_link: UntrustedText | None
    join_url: UntrustedText | None
    outcome: Literal["applied", "failed", "unverified"]
    error_code: str | None
    detail: str | None


class PeopleEntry(IntegrationFanOutEntry):
    data: PeopleData | None = None


class WriteEntry(IntegrationFanOutEntry):
    data: WriteData | None = None


class EventsOutput(IntegrationFanOutOutput):
    results: list[EventsEntry]


class EventOutput(IntegrationFanOutOutput):
    results: list[EventEntry]


class AvailabilityOutput(IntegrationFanOutOutput):
    results: list[AvailabilityEntry]


class MeetingTimesOutput(IntegrationFanOutOutput):
    results: list[MeetingTimesEntry]


class PeopleOutput(IntegrationFanOutOutput):
    results: list[PeopleEntry]


class WriteOutput(IntegrationFanOutOutput):
    results: list[WriteEntry]
