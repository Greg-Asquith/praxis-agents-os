// apps/web/src/features/schedules/components/schedule-cadence-field.tsx

import { CalendarIcon, RotateCcwIcon, TimerIcon } from "lucide-react"

import { Field, FieldLabel } from "@/components/ui/field"
import type {
  ScheduleFormFieldSetter,
  ScheduleFormState,
} from "@/features/schedules/components/schedule-form-model"
import { DEFAULT_CRON_EXPRESSION } from "@/features/schedules/components/schedule-form-model"
import type { ScheduleType } from "@/features/schedules/types"
import { cn } from "@/lib/utils"

const SCHEDULE_TYPE_OPTIONS: {
  description: string
  icon: typeof RotateCcwIcon
  label: string
  value: ScheduleType
}[] = [
  {
    description: "Run on a calendar pattern",
    icon: RotateCcwIcon,
    label: "Recurring",
    value: "cron",
  },
  {
    description: "Run every N minutes",
    icon: TimerIcon,
    label: "Interval",
    value: "interval",
  },
  {
    description: "Run at one time",
    icon: CalendarIcon,
    label: "One-time",
    value: "once",
  },
]

export function ScheduleCadenceField({
  setField,
  state,
}: {
  setField: ScheduleFormFieldSetter
  state: Pick<ScheduleFormState, "cronExpression" | "intervalMinutes" | "scheduleType">
}) {
  return (
    <Field>
      <FieldLabel>Cadence</FieldLabel>
      <div className="grid gap-2.5 sm:grid-cols-3" role="radiogroup">
        {SCHEDULE_TYPE_OPTIONS.map((option) => {
          const Icon = option.icon
          const selected = state.scheduleType === option.value

          return (
            <button
              aria-checked={selected}
              className={cn(
                "focus-visible:ring-ring/50 flex min-h-28 flex-col items-center justify-center gap-1.5 rounded-md border px-3 py-3 text-center text-sm transition-colors focus-visible:ring-3 focus-visible:outline-none",
                selected
                  ? "border-foreground/30 bg-muted text-foreground"
                  : "border-border bg-background text-muted-foreground hover:bg-muted/50 hover:text-foreground"
              )}
              key={option.value}
              onClick={() => {
                setField("scheduleType", option.value)
                if (option.value === "cron" && !state.cronExpression.trim()) {
                  setField("cronExpression", DEFAULT_CRON_EXPRESSION)
                }
                if (option.value === "interval" && !state.intervalMinutes.trim()) {
                  setField("intervalMinutes", "60")
                }
              }}
              role="radio"
              type="button"
            >
              <Icon className="size-4" aria-hidden="true" />
              <span className="font-medium">{option.label}</span>
              <span className="text-muted-foreground text-xs leading-5">{option.description}</span>
            </button>
          )
        })}
      </div>
    </Field>
  )
}
