// apps/web/src/integrations/outlook_calendar/lib/tool-details.ts

import { formatLocalDay, formatLocalTime } from "@/components/tool-ui/calendar/calendar-time"
import type { FanOutDetail } from "@/components/tool-ui/fan-out-shell"
import {
  compactDetails,
  listDetail,
  numberArg,
  stringArg,
  stringDetail,
} from "@/integrations/tool-details"

function windowDetail(args: unknown): FanOutDetail | null {
  const start = stringArg(args, "start")
  const end = stringArg(args, "end")
  if (!start || !end) return null
  const format = (value: string) => `${formatLocalDay(value)}, ${formatLocalTime(value)}`
  return { label: "When", value: `${format(start)} to ${format(end)}` }
}

function zoneDetail(args: unknown): FanOutDetail {
  return { label: "Time Zone", value: stringArg(args, "time_zone") ?? "Mailbox time zone" }
}

export function listEventsDetails(args: unknown): FanOutDetail[] {
  return compactDetails([windowDetail(args), zoneDetail(args)])
}

export function availabilityDetails(args: unknown): FanOutDetail[] {
  return compactDetails([
    listDetail(args, "addresses", "People"),
    windowDetail(args),
    zoneDetail(args),
  ])
}

export function meetingTimesDetails(args: unknown): FanOutDetail[] {
  const duration = numberArg(args, "duration_minutes") ?? 30
  return compactDetails([
    listDetail(args, "attendees", "Attendees"),
    windowDetail(args),
    { label: "Duration", value: `${String(duration)} minutes` },
    zoneDetail(args),
  ])
}

export function peopleDetails(args: unknown): FanOutDetail[] {
  return compactDetails([stringDetail(args, "query", "Name")])
}
