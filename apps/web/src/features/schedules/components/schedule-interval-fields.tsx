// apps/web/src/features/schedules/components/schedule-interval-fields.tsx

import { Field, FieldDescription, FieldError, FieldLabel } from "@/components/ui/field"
import { Input } from "@/components/ui/input"
import type { ScheduleFormFieldSetter } from "@/features/schedules/components/schedule-form-model"
import { formatIntervalMinutes } from "@/features/schedules/format"
import { cn } from "@/lib/utils"

const INTERVAL_QUICK_OPTIONS = [15, 30, 60, 360, 720, 1440]

export function ScheduleIntervalFields({
  error,
  intervalMinutes,
  setField,
}: {
  error: string | undefined
  intervalMinutes: string
  setField: ScheduleFormFieldSetter
}) {
  const parsedInterval = Number(intervalMinutes)
  const intervalLabel = Number.isInteger(parsedInterval)
    ? formatIntervalMinutes(parsedInterval)
    : "Custom interval"

  return (
    <div className="grid gap-4">
      <Field data-invalid={error ? true : undefined}>
        <FieldLabel htmlFor="schedule-interval">Run every</FieldLabel>
        <div className="grid gap-2 sm:grid-cols-3 lg:grid-cols-6">
          {INTERVAL_QUICK_OPTIONS.map((minutes) => (
            <button
              className={cn(
                "focus-visible:ring-ring/50 min-h-16 rounded-md border px-3 py-2 text-sm transition-colors focus-visible:ring-3 focus-visible:outline-none",
                String(minutes) === intervalMinutes
                  ? "border-foreground/30 bg-muted text-foreground"
                  : "border-border bg-background text-muted-foreground hover:bg-muted/50 hover:text-foreground"
              )}
              key={minutes}
              onClick={() => {
                setField("intervalMinutes", String(minutes))
              }}
              type="button"
            >
              {formatIntervalMinutes(minutes)}
            </button>
          ))}
        </div>
        <div className="mt-3 grid gap-3 sm:grid-cols-[minmax(0,12rem)_1fr] sm:items-center">
          <Input
            aria-invalid={error ? true : undefined}
            className="scroll-mt-20"
            id="schedule-interval"
            min={1}
            onChange={(event) => {
              setField("intervalMinutes", event.currentTarget.value)
            }}
            required
            type="number"
            value={intervalMinutes}
          />
          <FieldDescription>{intervalLabel}</FieldDescription>
        </div>
        <FieldError>{error}</FieldError>
      </Field>
    </div>
  )
}
