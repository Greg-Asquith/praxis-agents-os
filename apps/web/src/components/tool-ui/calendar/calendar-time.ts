// apps/web/src/components/tool-ui/calendar/calendar-time.ts

// Calendar tools return wall-clock times in a named zone, so these format without converting.
const LOCAL_DATE_TIME = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})(?::(\d{2}))?$/
const DAY_FORMATTER = new Intl.DateTimeFormat(undefined, {
  day: "numeric",
  month: "long",
  timeZone: "UTC",
  weekday: "long",
  year: "numeric",
})
const SHORT_DAY_FORMATTER = new Intl.DateTimeFormat(undefined, {
  day: "numeric",
  month: "short",
  timeZone: "UTC",
  weekday: "short",
})
const TIME_FORMATTER = new Intl.DateTimeFormat(undefined, {
  hour: "numeric",
  minute: "2-digit",
  timeZone: "UTC",
})

export function isLocalDateTime(value: unknown): value is string {
  return typeof value === "string" && parseLocalDateTime(value) !== null
}

function parseLocalDateTime(value: string): Date | null {
  const match = LOCAL_DATE_TIME.exec(value)
  if (!match) return null
  const [year, month, day, hour, minute] = match.slice(1, 6).map(Number) as [
    number,
    number,
    number,
    number,
    number,
  ]
  const date = new Date(Date.UTC(year, month - 1, day, hour, minute))
  return Number.isNaN(date.getTime()) ? null : date
}

function localDayKey(value: string): string {
  return value.slice(0, 10)
}

export function formatLocalDay(value: string): string {
  const date = parseLocalDateTime(value)
  return date ? DAY_FORMATTER.format(date) : "Unknown date"
}

export function formatLocalTime(value: string): string {
  const date = parseLocalDateTime(value)
  return date ? TIME_FORMATTER.format(date) : "Unknown time"
}

// All-day end dates are exclusive, so a one-day event ends at the next midnight.
export function formatLocalRange(start: string, end: string, allDay = false): string {
  const startDate = parseLocalDateTime(start)
  const endDate = parseLocalDateTime(end)
  if (!startDate || !endDate) return "Unknown time"
  if (allDay) {
    const lastDay = new Date(endDate.getTime() - 1)
    return localDayKey(lastDay.toISOString()) === localDayKey(start)
      ? "All day"
      : `All day until ${SHORT_DAY_FORMATTER.format(lastDay)}`
  }
  const endLabel =
    localDayKey(start) === localDayKey(end)
      ? TIME_FORMATTER.format(endDate)
      : `${SHORT_DAY_FORMATTER.format(endDate)}, ${TIME_FORMATTER.format(endDate)}`
  return `${TIME_FORMATTER.format(startDate)} - ${endLabel}`
}

export function timeZoneLabel(value: string): string {
  return value.replaceAll("_", " ")
}

export function groupByLocalDay<T>(items: T[], startOf: (item: T) => string): [string, T[]][] {
  const groups = new Map<string, T[]>()
  for (const item of items) {
    const key = localDayKey(startOf(item))
    groups.set(key, [...(groups.get(key) ?? []), item])
  }
  return [...groups.entries()]
}
