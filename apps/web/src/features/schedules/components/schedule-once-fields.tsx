// apps/web/src/features/schedules/components/schedule-once-fields.tsx

import { useState } from "react"

import { Field, FieldDescription, FieldError, FieldLabel } from "@/components/ui/field"
import { Input } from "@/components/ui/input"
import type { ScheduleFormFieldSetter } from "@/features/schedules/components/schedule-form-model"

const ONE_TIME_QUICK_OPTIONS = [
  {
    label: "In 1 hour",
    getValue: () => dateTimeLocalFromDate(addMinutes(new Date(), 60)),
  },
  {
    label: "Tomorrow at 9 AM",
    getValue: () => dateTimeLocalFromDate(nextDayAtHour(1, 9)),
  },
  {
    label: "Next Monday at 9 AM",
    getValue: () => dateTimeLocalFromDate(nextWeekdayAtHour(1, 9)),
  },
]

export function ScheduleOnceFields({
  error,
  runOnceAt,
  setField,
}: {
  error: string | undefined
  runOnceAt: string
  setField: ScheduleFormFieldSetter
}) {
  const [minRunOnceAt] = useState(() => dateTimeLocalFromDate(new Date()))

  return (
    <Field data-invalid={error ? true : undefined}>
      <FieldLabel htmlFor="schedule-once">Run at</FieldLabel>
      <div className="mb-3 flex flex-wrap gap-2">
        {ONE_TIME_QUICK_OPTIONS.map((option) => (
          <button
            className="border-border bg-background text-muted-foreground hover:bg-muted/50 hover:text-foreground focus-visible:ring-ring/50 rounded-md border px-3 py-1.5 text-xs font-medium transition-colors focus-visible:ring-3 focus-visible:outline-none"
            key={option.label}
            onClick={() => {
              setField("runOnceAt", option.getValue())
            }}
            type="button"
          >
            {option.label}
          </button>
        ))}
      </div>
      <Input
        aria-invalid={error ? true : undefined}
        className="scroll-mt-20"
        id="schedule-once"
        min={minRunOnceAt}
        onChange={(event) => {
          setField("runOnceAt", event.currentTarget.value)
        }}
        required
        type="datetime-local"
        value={runOnceAt}
      />
      <FieldDescription>
        Once-only schedules pause themselves after the run completes.
      </FieldDescription>
      <FieldError>{error}</FieldError>
    </Field>
  )
}

function addMinutes(date: Date, minutes: number) {
  return new Date(date.getTime() + minutes * 60_000)
}

function nextDayAtHour(daysFromNow: number, hour: number) {
  const next = new Date()
  next.setDate(next.getDate() + daysFromNow)
  next.setHours(hour, 0, 0, 0)
  return next
}

function nextWeekdayAtHour(targetDay: number, hour: number) {
  const next = new Date()
  const currentDay = next.getDay()
  const daysUntilTarget = (targetDay - currentDay + 7) % 7 || 7
  next.setDate(next.getDate() + daysUntilTarget)
  next.setHours(hour, 0, 0, 0)
  return next
}

function dateTimeLocalFromDate(date: Date) {
  const local = new Date(date.getTime() - date.getTimezoneOffset() * 60_000)
  return local.toISOString().slice(0, 16)
}
