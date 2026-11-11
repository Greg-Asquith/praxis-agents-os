// apps/web/src/integrations/google_ads/lib/ad-schedule.ts

import { isRecord } from "@/lib/guards"

export const DAYS = [
  "MONDAY",
  "TUESDAY",
  "WEDNESDAY",
  "THURSDAY",
  "FRIDAY",
  "SATURDAY",
  "SUNDAY",
] as const
export type Day = (typeof DAYS)[number]

// Times are HH:MM in quarter hours, in the account's time zone; a window can end at 24:00.
export type ScheduleWindow = { bidAdjustment: number | null; day: Day; end: string; start: string }

// Every hour of every day, which is what no windows means.
export const ALL_WEEK: readonly ScheduleWindow[] = DAYS.map((day) => ({
  bidAdjustment: null,
  day,
  end: "24:00",
  start: "00:00",
}))

/** Windows with the same times and adjustment, drawn as one row with the days they run on. */
export type ScheduleRow = { bidAdjustment: number | null; days: Day[]; end: string; start: string }

export type HourCell = "off" | "on" | "up" | "down"

// Google allows six windows a day.
const MAX_WINDOWS_PER_DAY = 6
const TIME = /^(\d{1,2})(?:[:.]?(\d{2}))?$/

export function dayShort(day: Day): string {
  return `${day.charAt(0)}${day.slice(1, 3).toLowerCase()}`
}

/** Reads a typed time such as 7, 7:30, or 0730 as HH:MM; null unless it's a quarter hour. */
export function parseTime(text: string): string | null {
  const match = TIME.exec(text.trim())
  if (!match) return null
  const hour = Number(match[1])
  const minute = Number(match[2] ?? "0")
  if (minute % 15 !== 0 || minute > 45 || hour > 24 || (hour === 24 && minute !== 0)) return null
  return `${String(hour).padStart(2, "0")}:${String(minute).padStart(2, "0")}`
}

function minutes(time: string): number {
  const [hour = 0, minute = 0] = time.split(":").map(Number)
  return hour * 60 + minute
}

export function parseWindows(value: unknown): ScheduleWindow[] {
  if (!Array.isArray(value)) return []
  return value.flatMap((item) => {
    if (!isRecord(item)) return []
    const { day, end, start } = item
    const bid = item["bid_adjustment"]
    if (
      typeof day !== "string" ||
      !(DAYS as readonly string[]).includes(day) ||
      typeof start !== "string" ||
      typeof end !== "string" ||
      parseTime(start) !== start ||
      parseTime(end) !== end
    )
      return []
    return [
      {
        bidAdjustment: typeof bid === "number" && Number.isInteger(bid) && bid !== 0 ? bid : null,
        day: day as Day,
        end,
        start,
      },
    ]
  })
}

export function windowEntry(window: ScheduleWindow): Record<string, unknown> {
  return {
    day: window.day,
    start: window.start,
    end: window.end,
    bid_adjustment: window.bidAdjustment,
  }
}

function sorted(windows: readonly ScheduleWindow[]): ScheduleWindow[] {
  return [...windows].sort(
    (left, right) =>
      DAYS.indexOf(left.day) - DAYS.indexOf(right.day) || minutes(left.start) - minutes(right.start)
  )
}

export function sameWindows(
  left: readonly ScheduleWindow[],
  right: readonly ScheduleWindow[]
): boolean {
  return JSON.stringify(sorted(left)) === JSON.stringify(sorted(right))
}

/** Groups windows by their times and adjustment, in the order each first appears. */
export function scheduleRows(windows: readonly ScheduleWindow[]): ScheduleRow[] {
  const rows: ScheduleRow[] = []
  for (const window of sorted(windows)) {
    // A window repeated on one day gets its own row, so the repeat shows as an overlap.
    const row = rows.find(
      (item) =>
        item.start === window.start &&
        item.end === window.end &&
        item.bidAdjustment === window.bidAdjustment &&
        !item.days.includes(window.day)
    )
    if (row) row.days.push(window.day)
    else rows.push({ ...window, days: [window.day] })
  }
  return rows
}

export function rowWindows(rows: readonly ScheduleRow[]): ScheduleWindow[] {
  return sorted(
    rows.flatMap((row) =>
      row.days.map((day) => ({
        bidAdjustment: row.bidAdjustment,
        day,
        end: row.end,
        start: row.start,
      }))
    )
  )
}

/**
 * Keeps the rows the operator built while they still make these windows, so a new row with
 * the same times as another stays its own row; any other change regroups the windows.
 */
export function keptRows<T extends ScheduleRow>(
  rows: readonly T[],
  windows: readonly ScheduleWindow[]
): readonly T[] | null {
  return sameWindows(rowWindows(rows), windows) ? rows : null
}

/** What's wrong with each row, or null; any problem blocks approval. */
export function scheduleProblems(rows: readonly ScheduleRow[]): (string | null)[] {
  const problems: (string | null)[] = rows.map((row) => {
    if (row.days.length === 0) return "Choose at least one day."
    return minutes(row.start) < minutes(row.end) ? null : "This window ends before it starts."
  })
  for (const day of DAYS) {
    const held = rows.flatMap((row, index) =>
      row.days.includes(day) && problems[index] === null ? [index] : []
    )
    for (const index of held) {
      const row = rows[index]
      if (!row) continue
      if (held.length > MAX_WINDOWS_PER_DAY) {
        problems[index] = `Google Ads allows ${String(MAX_WINDOWS_PER_DAY)} windows a day.`
        continue
      }
      const overlaps = held.some((other) => {
        const next = rows[other]
        return (
          other !== index &&
          next !== undefined &&
          minutes(next.start) < minutes(row.end) &&
          minutes(row.start) < minutes(next.end)
        )
      })
      if (overlaps) problems[index] = `Overlaps another window on ${dayShort(day)}.`
    }
  }
  return problems
}

export function scheduleValid(windows: readonly ScheduleWindow[]): boolean {
  // One row per window, so two windows with the same times on one day still count as overlapping.
  const rows = windows.map((window) => ({ ...window, days: [window.day] }))
  return rows.length > 0 && scheduleProblems(rows).every((problem) => problem === null)
}

function bidSuffix(bidAdjustment: number | null): string {
  if (bidAdjustment === null || bidAdjustment === 0) return ""
  return ` (${bidAdjustment > 0 ? "+" : ""}${String(bidAdjustment)}%)`
}

function dayRanges(days: readonly Day[]): string {
  const indexes = days.map((day) => DAYS.indexOf(day)).sort((a, b) => a - b)
  const ranges: string[] = []
  let start = indexes[0]
  for (let position = 0; position < indexes.length; position += 1) {
    const current = indexes[position]
    const next = indexes[position + 1]
    if (start === undefined || current === undefined) break
    if (next === current + 1) continue
    const first = DAYS[start]
    const last = DAYS[current]
    if (first && last)
      ranges.push(
        start === current
          ? dayShort(first)
          : `${dayShort(first)}${current - start === 1 ? ", " : "–"}${dayShort(last)}`
      )
    start = next
  }
  return ranges.join(", ")
}

/** The week in a line, such as "Mon–Fri 07:00–22:00"; no windows means ads run at any time. */
export function scheduleText(windows: readonly ScheduleWindow[]): string {
  if (windows.length === 0) return "Any time, every day"
  const byDay = new Map<Day, string>()
  for (const window of sorted(windows)) {
    const text = `${window.start}–${window.end}${bidSuffix(window.bidAdjustment)}`
    byDay.set(window.day, byDay.has(window.day) ? `${byDay.get(window.day) ?? ""}, ${text}` : text)
  }
  const groups = new Map<string, Day[]>()
  for (const [day, text] of byDay) groups.set(text, [...(groups.get(text) ?? []), day])
  return [...groups].map(([text, days]) => `${dayRanges(days)} ${text}`).join("; ")
}

/** One day as 24 hours: on when any window covers part of the hour, up or down with its bid. */
export function hourCells(windows: readonly ScheduleWindow[], day: Day): HourCell[] {
  const today = windows.filter((window) => window.day === day)
  return Array.from({ length: 24 }, (_unused, hour) => {
    const window = today.find(
      (item) => minutes(item.start) < (hour + 1) * 60 && hour * 60 < minutes(item.end)
    )
    if (!window) return "off"
    const bid = window.bidAdjustment ?? 0
    return bid > 0 ? "up" : bid < 0 ? "down" : "on"
  })
}
