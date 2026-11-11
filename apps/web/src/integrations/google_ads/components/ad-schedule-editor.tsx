// apps/web/src/integrations/google_ads/components/ad-schedule-editor.tsx

import { PlusIcon, XIcon } from "lucide-react"
import { useId, useState } from "react"

import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group"
import { BidAdjustment } from "@/integrations/google_ads/components/bid-adjustment"
import {
  ALL_WEEK,
  DAYS,
  dayShort,
  hourCells,
  keptRows,
  parseTime,
  rowWindows,
  scheduleProblems,
  scheduleRows,
  scheduleText,
  type Day,
  type HourCell,
  type ScheduleRow,
  type ScheduleWindow,
} from "@/integrations/google_ads/lib/ad-schedule"
import { cn } from "@/lib/utils"

const CELL_CLASSES: Record<HourCell, string> = {
  down: "bg-primary/35",
  off: "bg-muted",
  on: "bg-primary/65",
  up: "bg-primary",
}
const HOURS = Array.from({ length: 24 }, (_unused, hour) => hour)
const HOUR_LABELS = new Set([0, 6, 12, 18])
const NEW_WINDOW = { bidAdjustment: null, end: "17:00", start: "09:00" }

// A row with a stable identity, so edits and new rows keep their place and focus.
type EditorRow = ScheduleRow & { id: number }

let nextRowId = 0

function editorRows(windows: readonly ScheduleWindow[]): EditorRow[] {
  return scheduleRows(windows).map((row) => ({ ...row, id: (nextRowId += 1) }))
}

/** The week as a grid of hours in the account's time zone, darker where bids go up. */
export function ScheduleGrid({
  label,
  windows,
}: {
  label: string
  // No windows means ads can show at any time.
  windows: readonly ScheduleWindow[]
}) {
  const text = scheduleText(windows)
  const shown = windows.length === 0 ? ALL_WEEK : windows
  const ups = shown.some((window) => (window.bidAdjustment ?? 0) > 0)
  const downs = shown.some((window) => (window.bidAdjustment ?? 0) < 0)
  return (
    <div className="grid min-w-0 content-start gap-1.5">
      <p className="text-sm wrap-anywhere">
        <span className="font-medium">{label}:</span>{" "}
        <span className="text-muted-foreground">{text}</span>
      </p>
      <div
        aria-label={`${label}: ${text}`}
        className="grid grid-cols-[2.5rem_repeat(24,minmax(0,1fr))] gap-0.5 text-[0.65rem]"
        role="img"
      >
        <span />
        {HOURS.map((hour) => (
          <span key={hour} className="text-muted-foreground text-center tabular-nums">
            {HOUR_LABELS.has(hour) ? String(hour) : ""}
          </span>
        ))}
        {DAYS.map((day) => (
          <Day key={day} day={day} windows={shown} />
        ))}
      </div>
      {ups || downs ? (
        <p className="text-muted-foreground flex flex-wrap gap-3 text-xs">
          {ups ? <Legend cell="up" label="Higher bids" /> : null}
          {downs ? <Legend cell="down" label="Lower bids" /> : null}
        </p>
      ) : null}
    </div>
  )
}

function Day({ day, windows }: { day: Day; windows: readonly ScheduleWindow[] }) {
  const cells = hourCells(windows, day)
  return (
    <>
      <span className="text-muted-foreground self-center">{dayShort(day)}</span>
      {HOURS.map((hour) => (
        <span key={hour} className={cn("h-3 rounded-[2px]", CELL_CLASSES[cells[hour] ?? "off"])} />
      ))}
    </>
  )
}

function Legend({ cell, label }: { cell: HourCell; label: string }) {
  return (
    <span className="flex items-center gap-1">
      <span aria-hidden="true" className={cn("size-2.5 rounded-[2px]", CELL_CLASSES[cell])} />
      {label}
    </span>
  )
}

/** The week's windows, one row per set of days sharing times and an adjustment. */
export function ScheduleWindows({
  disabled,
  onChange,
  windows,
}: {
  disabled: boolean
  onChange: (windows: ScheduleWindow[]) => void
  windows: readonly ScheduleWindow[]
}) {
  const [held, setHeld] = useState<readonly EditorRow[]>(() => editorRows(windows))
  // Windows changed from outside, such as another campaign chosen, start the rows again.
  const rows = keptRows(held, windows) ?? editorRows(windows)
  if (rows !== held) setHeld(rows)
  const problems = scheduleProblems(rows)
  const baseId = useId()
  // Typed times that were refused, by row and end, so the row can say why its time went back.
  const [refused, setRefused] = useState<Record<string, string>>({})
  const save = (next: readonly EditorRow[]) => {
    setHeld(next)
    onChange(rowWindows(next))
  }
  const edit = (index: number, patch: Partial<ScheduleRow>) => {
    save(rows.map((row, position) => (position === index ? { ...row, ...patch } : row)))
  }
  // A new window starts on the quietest day, so it rarely overlaps one already there.
  const quietest = [...DAYS].sort(
    (left, right) =>
      windows.filter((window) => window.day === left).length -
      windows.filter((window) => window.day === right).length
  )[0]
  return (
    <div className="grid min-w-0 gap-2">
      <div className="divide-y rounded-lg border">
        {rows.map((row, index) => {
          const position = String(index + 1)
          const problemId = problems[index] ? `${baseId}-${String(row.id)}-problem` : null
          const time = (end: "start" | "end") => {
            const key = `${String(row.id)}-${end}`
            const text = refused[key]
            return {
              describedBy: [text ? `${baseId}-${key}` : null, problemId].filter(Boolean).join(" "),
              key,
              onRefuse: (typed: string | null) => {
                setRefused(({ [key]: _old, ...rest }) =>
                  typed === null ? rest : { ...rest, [key]: typed }
                )
              },
              text,
            }
          }
          const from = time("start")
          const to = time("end")
          return (
            <div key={row.id} className="grid min-w-0 gap-1 py-1.5 pr-1.5 pl-3">
              <div className="flex min-w-0 flex-wrap items-center gap-2">
                <DayPicker
                  days={row.days}
                  describedBy={problemId}
                  disabled={disabled}
                  label={`Days for window ${position}`}
                  onChange={(days) => {
                    edit(index, { days })
                  }}
                />
                <TimeInput
                  describedBy={from.describedBy}
                  disabled={disabled}
                  label={`Start time for window ${position}`}
                  onChange={(start) => {
                    edit(index, { start })
                  }}
                  onRefuse={from.onRefuse}
                  value={row.start}
                />
                <span aria-hidden="true" className="text-muted-foreground text-sm">
                  to
                </span>
                <TimeInput
                  describedBy={to.describedBy}
                  disabled={disabled}
                  label={`End time for window ${position}`}
                  onChange={(end) => {
                    edit(index, { end })
                  }}
                  onRefuse={to.onRefuse}
                  value={row.end}
                />
                <BidAdjustment
                  disabled={disabled}
                  label={`Bid adjustment from ${row.start} to ${row.end}`}
                  onChange={(bidAdjustment) => {
                    edit(index, { bidAdjustment: bidAdjustment === 0 ? null : bidAdjustment })
                  }}
                  value={row.bidAdjustment}
                />
                <Button
                  aria-label={`Remove the window from ${row.start} to ${row.end}`}
                  className="ml-auto size-11 shrink-0"
                  disabled={disabled || rows.length === 1}
                  onClick={() => {
                    save(rows.filter((_row, position) => position !== index))
                  }}
                  size="icon"
                  title="Remove This Window"
                  type="button"
                  variant="ghost"
                >
                  <XIcon aria-hidden="true" />
                </Button>
              </div>
              {[from, to].map((end) =>
                end.text ? (
                  <p
                    key={end.key}
                    className="text-destructive text-sm"
                    id={`${baseId}-${end.key}`}
                    role="alert"
                  >
                    {`"${end.text}" isn't a quarter hour, so this time is still ${
                      end === from ? row.start : row.end
                    }. Use a time such as 07:15.`}
                  </p>
                ) : null
              )}
              {problemId ? (
                <p className="text-destructive text-sm" id={problemId} role="alert">
                  {problems[index]}
                </p>
              ) : null}
            </div>
          )
        })}
      </div>
      <Button
        className="w-fit"
        disabled={disabled || quietest === undefined}
        onClick={() => {
          if (quietest) save([...rows, { ...NEW_WINDOW, days: [quietest], id: (nextRowId += 1) }])
        }}
        size="sm"
        type="button"
        variant="ghost"
      >
        <PlusIcon aria-hidden="true" />
        Add Time Window
      </Button>
    </div>
  )
}

function DayPicker({
  days,
  describedBy,
  disabled,
  label,
  onChange,
}: {
  days: readonly Day[]
  describedBy: string | null
  disabled: boolean
  label: string
  onChange: (days: Day[]) => void
}) {
  return (
    <ToggleGroup
      aria-describedby={describedBy ?? undefined}
      aria-label={label}
      className="bg-background rounded-lg border p-0.5"
      disabled={disabled}
      multiple
      onValueChange={(next) => {
        const chosen = DAYS.filter((day) => next.includes(day))
        // A window needs a day, so the last one can't be turned off.
        if (chosen.length > 0) onChange(chosen)
      }}
      spacing={0.5}
      value={[...days]}
    >
      {DAYS.map((day) => (
        <ToggleGroupItem
          key={day}
          aria-label={dayShort(day)}
          className="text-muted-foreground aria-pressed:bg-accent aria-pressed:text-accent-foreground h-7 min-w-8 px-1.5 text-xs aria-pressed:font-semibold"
          value={day}
        >
          {dayShort(day).slice(0, 2)}
        </ToggleGroupItem>
      ))}
    </ToggleGroup>
  )
}

/** A time typed as 7, 7:30, or 07:30; anything but a quarter hour goes back to the last time. */
function TimeInput({
  describedBy,
  disabled,
  label,
  onChange,
  onRefuse,
  value,
}: {
  describedBy: string
  disabled: boolean
  label: string
  onChange: (value: string) => void
  // The typed text that was refused, or null once the operator types again.
  onRefuse: (typed: string | null) => void
  value: string
}) {
  const [draft, setDraft] = useState<string | null>(null)
  const text = draft ?? value
  const parsed = parseTime(text)
  return (
    <Input
      aria-describedby={describedBy || undefined}
      aria-invalid={parsed === null}
      aria-label={label}
      className={cn("w-18 text-center tabular-nums", parsed === null && "border-destructive")}
      disabled={disabled}
      onBlur={() => {
        // The request still holds the last valid time, so the input shows it again.
        setDraft(null)
        if (parsed === null) onRefuse(text)
        else if (parsed !== value) onChange(parsed)
      }}
      onChange={(event) => {
        setDraft(event.currentTarget.value)
        onRefuse(null)
      }}
      placeholder="00:00"
      title="Quarter hours, such as 07:15"
      value={text}
    />
  )
}
