// apps/web/src/features/schedules/components/schedule-cron-advanced-builder.tsx

import { CheckIcon } from "lucide-react"

import { Field, FieldLabel } from "@/components/ui/field"
import { Input } from "@/components/ui/input"
import {
  buildAdvancedCron,
  DAY_OPTIONS,
  type AdvancedCronValues,
} from "@/features/schedules/components/schedule-cron-model"
import { formatCronExpression } from "@/features/schedules/format"
import { cn } from "@/lib/utils"

export function ScheduleCronAdvancedBuilder({
  onChange,
  value,
}: {
  onChange: (value: AdvancedCronValues) => void
  value: AdvancedCronValues
}) {
  const advancedCron = buildAdvancedCron(value.days, value.hour, value.minute)
  const advancedPreview = advancedCron ? formatCronExpression(advancedCron) : "Choose a valid time"

  function handleDayToggle(dayValue: string) {
    const selected = value.days.includes(dayValue)
    if (selected && value.days.length === 1) {
      return
    }

    onChange({
      ...value,
      days: selected
        ? value.days.filter((current) => current !== dayValue)
        : [...value.days, dayValue],
    })
  }

  return (
    <div className="bg-muted/30 grid gap-4 rounded-md border p-4">
      <Field>
        <FieldLabel>Days of the week</FieldLabel>
        <div className="flex flex-wrap gap-2">
          {DAY_OPTIONS.map((day) => {
            const selected = value.days.includes(day.value)

            return (
              <button
                aria-pressed={selected}
                className={cn(
                  "focus-visible:ring-ring/50 rounded-md border px-3 py-1.5 text-xs font-medium transition-colors focus-visible:ring-3 focus-visible:outline-none",
                  selected
                    ? "border-foreground/30 bg-foreground text-background"
                    : "border-border bg-background text-muted-foreground hover:bg-muted hover:text-foreground"
                )}
                key={day.value}
                onClick={() => {
                  handleDayToggle(day.value)
                }}
                type="button"
              >
                {selected ? <CheckIcon data-icon="inline-start" /> : null}
                {day.label}
              </button>
            )
          })}
        </div>
      </Field>

      <div className="grid gap-4 sm:grid-cols-2">
        <Field>
          <FieldLabel htmlFor="schedule-advanced-hour">Hour</FieldLabel>
          <Input
            id="schedule-advanced-hour"
            max={23}
            min={0}
            onChange={(event) => {
              onChange({
                ...value,
                hour: event.currentTarget.value,
              })
            }}
            type="number"
            value={value.hour}
          />
        </Field>
        <Field>
          <FieldLabel htmlFor="schedule-advanced-minute">Minute</FieldLabel>
          <Input
            id="schedule-advanced-minute"
            max={59}
            min={0}
            onChange={(event) => {
              onChange({
                ...value,
                minute: event.currentTarget.value,
              })
            }}
            type="number"
            value={value.minute}
          />
        </Field>
      </div>

      <p className="text-muted-foreground text-xs">
        Preview: <span className="text-foreground">{advancedPreview}</span>
      </p>
    </div>
  )
}
