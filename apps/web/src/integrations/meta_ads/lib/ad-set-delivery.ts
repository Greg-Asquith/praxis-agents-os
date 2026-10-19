// apps/web/src/integrations/meta_ads/lib/ad-set-delivery.ts

import { isOneOf, isRecord } from "@/lib/guards"

// Meta's day order, from 0 for Sunday, as the server's tools/schemas/delivery.py.
const WEEKDAYS = [
  "sunday",
  "monday",
  "tuesday",
  "wednesday",
  "thursday",
  "friday",
  "saturday",
] as const
export type Weekday = (typeof WEEKDAYS)[number]
const WEEKDAY_SET: ReadonlySet<Weekday> = new Set(WEEKDAYS)
// The card's week starts on Monday.
export const WEEK: readonly Weekday[] = [...WEEKDAYS.slice(1), "sunday"]
export const DAY_LABELS: Record<Weekday, string> = {
  monday: "Mon",
  tuesday: "Tue",
  wednesday: "Wed",
  thursday: "Thu",
  friday: "Fri",
  saturday: "Sat",
  sunday: "Sun",
}
export const MAX_SCHEDULE_WINDOWS = 7
// The ad set settings with a structured value.
export type DeliveryKind = "attribution" | "frequency" | "schedule"
export const DELIVERY_KINDS: ReadonlySet<string> = new Set<DeliveryKind>([
  "attribution",
  "frequency",
  "schedule",
])

export type Attribution = { click_days: number; view_days: number; engaged_view_days: number }
export type FrequencyCap = { max_impressions: number; every_days: number }
export type ScheduleWindow = { days: Weekday[]; start_hour: number; end_hour: number }
export type AdSchedule = { time_zone: "viewer" | "account"; windows: ScheduleWindow[] }

export const WEEKDAY_EVENINGS: AdSchedule = {
  time_zone: "viewer",
  windows: [
    {
      days: ["monday", "tuesday", "wednesday", "thursday", "friday"],
      start_hour: 18,
      end_hour: 22,
    },
  ],
}

function wholeNumber(value: unknown): number | null {
  return typeof value === "number" && Number.isInteger(value) ? value : null
}

export function parseAttribution(value: unknown): Attribution | null {
  if (!isRecord(value)) return null
  const click = wholeNumber(value["click_days"])
  const view = value["view_days"] === undefined ? 0 : wholeNumber(value["view_days"])
  const engaged =
    value["engaged_view_days"] === undefined ? 0 : wholeNumber(value["engaged_view_days"])
  if (click === null || view === null || engaged === null) return null
  return { click_days: click, view_days: view, engaged_view_days: engaged }
}

export function parseFrequencyCap(value: unknown): FrequencyCap | null {
  if (!isRecord(value)) return null
  const times = wholeNumber(value["max_impressions"])
  const days = wholeNumber(value["every_days"])
  return times === null || days === null ? null : { max_impressions: times, every_days: days }
}

export function parseAdSchedule(value: unknown): AdSchedule | null {
  if (!isRecord(value) || !Array.isArray(value["windows"])) return null
  const windows: ScheduleWindow[] = []
  for (const item of value["windows"]) {
    if (!isRecord(item) || !Array.isArray(item["days"])) return null
    const start = wholeNumber(item["start_hour"])
    const end = wholeNumber(item["end_hour"])
    const days = item["days"].filter((day): day is Weekday => isOneOf(WEEKDAY_SET, day))
    if (start === null || end === null || days.length !== item["days"].length) return null
    windows.push({ days, start_hour: start, end_hour: end })
  }
  const zone = value["time_zone"] ?? "viewer"
  if (zone !== "viewer" && zone !== "account") return null
  return { time_zone: zone, windows }
}

/** The one text form of a value, so the card's values compare with the server's checks. */
export function deliveryText(kind: DeliveryKind, value: unknown): string | null {
  if (kind === "attribution") {
    const attribution = parseAttribution(value)
    return attribution ? JSON.stringify(attribution) : null
  }
  if (kind === "frequency") {
    const cap = parseFrequencyCap(value)
    return cap ? JSON.stringify(cap) : null
  }
  const schedule = parseAdSchedule(value)
  if (schedule === null) return null
  const windows = schedule.windows
    .map((window) => ({
      days: [...window.days].sort((a, b) => WEEKDAYS.indexOf(a) - WEEKDAYS.indexOf(b)),
      start_hour: window.start_hour,
      end_hour: window.end_hour,
    }))
    .sort(
      (a, b) =>
        WEEKDAYS.indexOf(a.days[0] ?? "sunday") - WEEKDAYS.indexOf(b.days[0] ?? "sunday") ||
        a.start_hour - b.start_hour
    )
  return JSON.stringify({ time_zone: schedule.time_zone, windows })
}

/** Reads a value the server or the card wrote as text. */
export function fromText(text: string): unknown {
  try {
    return JSON.parse(text) as unknown
  } catch {
    return null
  }
}

function days(count: number, word: string): string {
  return `${String(count)}-day ${word}`
}

export function formatAttribution(value: Attribution): string {
  return [
    days(value.click_days, "click"),
    ...(value.view_days ? [days(value.view_days, "view")] : []),
    ...(value.engaged_view_days ? [days(value.engaged_view_days, "engaged view")] : []),
  ].join(", ")
}

export function formatFrequencyCap(value: FrequencyCap): string {
  const times = value.max_impressions === 1 ? "once" : `${String(value.max_impressions)} times`
  const every = value.every_days === 1 ? "a day" : `every ${String(value.every_days)} days`
  return `At most ${times} ${every}`
}

export function formatHour(hour: number): string {
  return `${String(hour).padStart(2, "0")}:00`
}

/** Days as Monday-first ranges, such as "Mon to Fri" or "Mon, Wed". */
function formatDays(chosen: readonly Weekday[]): string {
  const indexes = WEEK.map((day) => chosen.includes(day))
  const runs: string[] = []
  for (let start = 0; start < WEEK.length; start++) {
    if (!indexes[start]) continue
    let end = start
    while (end + 1 < WEEK.length && indexes[end + 1]) end++
    const first = DAY_LABELS[WEEK[start] ?? "monday"]
    const last = DAY_LABELS[WEEK[end] ?? "monday"]
    runs.push(end - start >= 2 ? `${first} to ${last}` : end > start ? `${first}, ${last}` : first)
    start = end
  }
  return runs.join(", ")
}

export function formatAdSchedule(value: AdSchedule): string {
  const windows = value.windows
    .map(
      (window) =>
        `${formatDays(window.days)} ${formatHour(window.start_hour)} to ${formatHour(window.end_hour)}`
    )
    .join("; ")
  return `${windows} (${value.time_zone === "viewer" ? "each viewer's time" : "ad account time"})`
}

/** Whether the schedule runs the ads during this hour of this day. */
export function scheduleCovers(value: AdSchedule, day: Weekday, hour: number): boolean {
  return value.windows.some(
    (window) => window.days.includes(day) && hour >= window.start_hour && hour < window.end_hour
  )
}

export function frequencyCapProblem(value: unknown): string | null {
  const cap = parseFrequencyCap(value)
  const valid = (count: number) => count >= 1 && count <= 90
  return cap && valid(cap.max_impressions) && valid(cap.every_days)
    ? null
    : "Enter whole numbers from 1 to 90."
}

export function adScheduleProblem(value: unknown): string | null {
  const schedule = parseAdSchedule(value)
  if (schedule === null || schedule.windows.length === 0) return "Add at least one time window."
  if (schedule.windows.length > MAX_SCHEDULE_WINDOWS)
    return `Use at most ${String(MAX_SCHEDULE_WINDOWS)} time windows.`
  if (schedule.windows.some((window) => window.days.length === 0))
    return "Choose at least one day for each time window."
  if (schedule.windows.some((window) => window.end_hour <= window.start_hour))
    return "End each time window after it starts."
  const taken = new Set<string>()
  for (const window of schedule.windows)
    for (const day of window.days)
      for (let hour = window.start_hour; hour < window.end_hour; hour++) {
        const key = `${day}:${String(hour)}`
        if (taken.has(key)) return "Time windows on the same day can't overlap."
        taken.add(key)
      }
  return null
}
