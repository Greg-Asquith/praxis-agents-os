// apps/web/src/integrations/outlook_calendar/lib/write-args.ts

import { isLocalDateTime } from "@/components/tool-ui/calendar/calendar-time"
import type { CalendarEventDraft } from "@/components/tool-ui/calendar/calendar-event-list"
import { isRecord, isStringArray } from "@/lib/guards"

export type OutlookEventReference = { calendarId: string; eventId: string; label: string }

export type OutlookCreateEventArgs = CalendarEventDraft & {
  attendees: string[]
  end: string
  online: boolean
  showAs: string
  start: string
  title: string
}
export type OutlookUpdateEventArgs = CalendarEventDraft & { event: OutlookEventReference }
export type OutlookRespondArgs = {
  comment: string
  event: OutlookEventReference
  response: "accept" | "decline" | "tentative"
  sendResponse: boolean
}
export type OutlookCancelArgs = { comment: string; event: OutlookEventReference }

const RESPONSES = new Set(["accept", "decline", "tentative"])

export function outlookEventReference(value: unknown): OutlookEventReference | null {
  if (
    !isRecord(value) ||
    value["entity_kind"] !== "outlook_event" ||
    typeof value["calendar_id"] !== "string" ||
    !value["calendar_id"] ||
    typeof value["event_id"] !== "string" ||
    !value["event_id"]
  ) {
    return null
  }
  const label = typeof value["label"] === "string" ? value["label"].trim() : ""
  return {
    calendarId: value["calendar_id"],
    eventId: value["event_id"],
    label: label || "Outlook event",
  }
}

function optionalText(value: unknown): string | null | undefined {
  if (value == null) return null
  return typeof value === "string" ? value : undefined
}

function optionalTime(value: unknown): string | null | undefined {
  if (value == null) return null
  return isLocalDateTime(value) ? value : undefined
}

function optionalAttendees(value: unknown): string[] | null | undefined {
  if (value == null) return null
  return isStringArray(value) ? value : undefined
}

export function outlookCreateEventArgs(value: unknown): OutlookCreateEventArgs | null {
  if (!isRecord(value)) return null
  const { start, end } = value
  const title = value["subject"]
  const attendees = optionalAttendees(value["attendees"])
  const timeZone = optionalText(value["time_zone"])
  const location = optionalText(value["location"])
  if (
    typeof title !== "string" ||
    !isLocalDateTime(start) ||
    !isLocalDateTime(end) ||
    attendees === undefined ||
    timeZone === undefined ||
    location === undefined
  ) {
    return null
  }
  return {
    allDay: value["is_all_day"] === true,
    attendees: attendees ?? [],
    end,
    location,
    online: value["is_online_meeting"] === true,
    showAs: typeof value["show_as"] === "string" ? value["show_as"] : "busy",
    start,
    timeZone,
    title,
  }
}

export function outlookUpdateEventArgs(value: unknown): OutlookUpdateEventArgs | null {
  if (!isRecord(value)) return null
  const event = outlookEventReference(value["event"])
  const title = optionalText(value["subject"])
  const start = optionalTime(value["start"])
  const end = optionalTime(value["end"])
  const timeZone = optionalText(value["time_zone"])
  const attendees = optionalAttendees(value["attendees"])
  const location = optionalText(value["location"])
  if (
    !event ||
    [title, start, end, timeZone, attendees, location].some((item) => item === undefined)
  ) {
    return null
  }
  return {
    allDay: false,
    attendees: attendees ?? null,
    end: end ?? null,
    event,
    location: location ?? null,
    online: null,
    start: start ?? null,
    timeZone: timeZone ?? null,
    title: title ?? null,
  }
}

// Mirrors the server rule, so the card explains a half-moved event before approval.
export function validateOutlookUpdateEventArgs(value: unknown): string | null {
  const args = outlookUpdateEventArgs(value)
  if (!args) return null
  if ((args.start === null) !== (args.end === null)) return "Set Start and End together."
  if (args.start !== null && args.end !== null && args.end <= args.start) {
    return "End must be after Start."
  }
  return null
}

export function validateOutlookCreateEventArgs(value: unknown): string | null {
  const args = outlookCreateEventArgs(value)
  return args && args.end <= args.start ? "End must be after Start." : null
}

export function outlookRespondArgs(value: unknown): OutlookRespondArgs | null {
  if (!isRecord(value)) return null
  const event = outlookEventReference(value["event"])
  const response = value["response"]
  const comment = optionalText(value["comment"])
  if (!event || typeof response !== "string" || !RESPONSES.has(response) || comment === undefined) {
    return null
  }
  return {
    comment: comment ?? "",
    event,
    response: response as OutlookRespondArgs["response"],
    sendResponse: value["send_response"] !== false,
  }
}

export function outlookCancelArgs(value: unknown): OutlookCancelArgs | null {
  if (!isRecord(value)) return null
  const event = outlookEventReference(value["event"])
  const comment = optionalText(value["comment"])
  return event && comment !== undefined ? { comment: comment ?? "", event } : null
}
