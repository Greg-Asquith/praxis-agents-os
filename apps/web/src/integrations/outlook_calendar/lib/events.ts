// apps/web/src/integrations/outlook_calendar/lib/events.ts

import { isLocalDateTime } from "@/components/tool-ui/calendar/calendar-time"
import { nodeText } from "@/components/tool-ui/untrusted-node"
import type { DataRow } from "@/components/ui/data-table-model"
import { isNonNegativeInteger, isRecord, isStringArray } from "@/lib/guards"

export const RESPONSE_LABELS: Record<string, string> = {
  accepted: "Accepted",
  declined: "Declined",
  notResponded: "Not Responded",
  organizer: "Organiser",
  tentativelyAccepted: "Tentative",
}

export const AVAILABILITY_LABELS: Record<string, string> = {
  busy: "Busy",
  free: "Free",
  oof: "Out of Office",
  tentative: "Tentative",
  unknown: "Unknown",
  workingElsewhere: "Working Elsewhere",
}

export type OutlookEvent = {
  allDay: boolean
  attendeeCount: number
  cancelled: boolean
  end: string
  eventId: string
  location: string
  online: boolean
  organizer: string
  private: boolean
  response: string
  showAs: string
  start: string
  subject: string
  timeZone: string
}

type OutlookAttendee = { address: string; name: string; status: string; type: string }

export type OutlookEventDetail = OutlookEvent & {
  attendees: OutlookAttendee[]
  body: string
  recurrence: string | null
  truncated: boolean
}

export type OutlookEvents = { events: OutlookEvent[]; timeZone: string }

type OutlookBusyPeriod = { end: string; start: string; status: string }

export type OutlookSchedule = {
  address: string
  available: boolean
  busyPeriods: OutlookBusyPeriod[]
  workingHours: string | null
}

export type OutlookAvailability = { schedules: OutlookSchedule[]; timeZone: string }

export type OutlookSuggestion = {
  attendees: { address: string; availability: string }[]
  confidence: number | null
  end: string
  start: string
}

export type OutlookMeetingTimes = {
  emptyReason: string | null
  suggestions: OutlookSuggestion[]
  timeZone: string
}

function person(value: unknown): string | null {
  if (!isRecord(value)) return null
  const address = nodeText(value["address"])
  const name = nodeText(value["name"])?.trim()
  if (address === null) return null
  return name && name !== address ? `${name} <${address}>` : address
}

function list<T>(value: unknown, parse: (item: unknown) => T | null): T[] | null {
  if (!Array.isArray(value)) return null
  const items: T[] = []
  for (const item of value) {
    const parsed = parse(item)
    if (parsed === null) return null
    items.push(parsed)
  }
  return items
}

function event(value: unknown): OutlookEvent | null {
  if (!isRecord(value) || !isRecord(value["reference"])) return null
  const eventId = value["reference"]["event_id"]
  const subject = nodeText(value["subject"])
  const location = nodeText(value["location"])
  const organizer = person(value["organizer"])
  const { start, end } = value
  if (
    typeof eventId !== "string" ||
    subject === null ||
    location === null ||
    organizer === null ||
    !isLocalDateTime(start) ||
    !isLocalDateTime(end) ||
    typeof value["time_zone"] !== "string" ||
    !isNonNegativeInteger(value["attendee_count"])
  )
    return null
  return {
    allDay: value["is_all_day"] === true,
    attendeeCount: value["attendee_count"],
    cancelled: value["is_cancelled"] === true,
    end,
    eventId,
    location,
    online: value["is_online_meeting"] === true,
    organizer,
    private: value["sensitivity"] === "private" || value["sensitivity"] === "confidential",
    response: typeof value["response_status"] === "string" ? value["response_status"] : "none",
    showAs: typeof value["show_as"] === "string" ? value["show_as"] : "unknown",
    start,
    subject,
    timeZone: value["time_zone"],
  }
}

function attendee(value: unknown): OutlookAttendee | null {
  if (!isRecord(value)) return null
  const name = nodeText(value["name"])
  const address = nodeText(value["address"])
  if (name === null || address === null) return null
  return {
    address,
    name,
    status: typeof value["status"] === "string" ? value["status"] : "none",
    type: typeof value["type"] === "string" ? value["type"] : "required",
  }
}

export function parseEvents(value: unknown): OutlookEvents | null {
  if (!isRecord(value) || typeof value["time_zone"] !== "string") return null
  const events = list(value["events"], event)
  return events ? { events, timeZone: value["time_zone"] } : null
}

export function parseEventDetail(value: unknown): OutlookEventDetail | null {
  const summary = event(value)
  if (!summary || !isRecord(value)) return null
  const body = nodeText(value["body"])
  const attendees = list(value["attendees"], attendee)
  if (body === null || attendees === null) return null
  return {
    ...summary,
    attendees,
    body,
    recurrence:
      typeof value["recurrence_summary"] === "string" ? value["recurrence_summary"] : null,
    truncated: value["truncated"] === true,
  }
}

function busyPeriod(value: unknown): OutlookBusyPeriod | null {
  if (!isRecord(value) || typeof value["status"] !== "string") return null
  const { start, end } = value
  return isLocalDateTime(start) && isLocalDateTime(end)
    ? { end, start, status: value["status"] }
    : null
}

function workingHours(value: unknown): string | null {
  if (
    !isRecord(value) ||
    !isStringArray(value["days"]) ||
    typeof value["start_time"] !== "string" ||
    typeof value["end_time"] !== "string"
  )
    return null
  const days = value["days"].map((day) => day.slice(0, 1).toUpperCase() + day.slice(1, 3))
  const zone = typeof value["time_zone"] === "string" ? ` ${value["time_zone"]}` : ""
  return `${days.join(", ")} ${value["start_time"].slice(0, 5)} - ${value["end_time"].slice(0, 5)}${zone}`
}

function schedule(value: unknown): OutlookSchedule | null {
  if (!isRecord(value) || typeof value["address"] !== "string") return null
  const busyPeriods = list(value["busy_periods"], busyPeriod)
  if (busyPeriods === null) return null
  return {
    address: value["address"],
    available: value["available"] === true,
    busyPeriods,
    workingHours: workingHours(value["working_hours"]),
  }
}

export function parseAvailability(value: unknown): OutlookAvailability | null {
  if (!isRecord(value) || typeof value["time_zone"] !== "string") return null
  const schedules = list(value["schedules"], schedule)
  return schedules ? { schedules, timeZone: value["time_zone"] } : null
}

function suggestion(value: unknown): OutlookSuggestion | null {
  if (!isRecord(value)) return null
  const { start, end, confidence } = value
  const attendees = list(value["attendee_availability"], (item) =>
    isRecord(item) &&
    typeof item["address"] === "string" &&
    typeof item["availability"] === "string"
      ? { address: item["address"], availability: item["availability"] }
      : null
  )
  if (!isLocalDateTime(start) || !isLocalDateTime(end) || attendees === null) return null
  return { attendees, confidence: typeof confidence === "number" ? confidence : null, end, start }
}

export function parseMeetingTimes(value: unknown): OutlookMeetingTimes | null {
  if (!isRecord(value) || typeof value["time_zone"] !== "string") return null
  const suggestions = list(value["suggestions"], suggestion)
  if (suggestions === null) return null
  const reason = value["empty_suggestions_reason"]
  return {
    emptyReason: typeof reason === "string" ? reason : null,
    suggestions,
    timeZone: value["time_zone"],
  }
}

export function peopleRows(value: unknown): DataRow[] | null {
  if (!isRecord(value)) return null
  const fields = ["name", "address", "job_title", "department"]
  return list(value["people"], (item) => {
    if (!isRecord(item)) return null
    const cells = fields.map((key) => nodeText(item[key]))
    if (cells.some((cell) => cell === null)) return null
    return Object.fromEntries(fields.map((key, index) => [key, cells[index]]))
  })
}
