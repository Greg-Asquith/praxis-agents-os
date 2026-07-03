// apps/web/src/features/schedules/components/schedule-cron-fields.tsx

import { Field, FieldDescription, FieldError, FieldLabel } from "@/components/ui/field"
import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectLabel,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import type { ScheduleFormFieldSetter } from "@/features/schedules/components/schedule-form-model"
import { ScheduleCronAdvancedBuilder } from "@/features/schedules/components/schedule-cron-advanced-builder"
import {
  buildAdvancedCron,
  CRON_PRESETS,
  DEFAULT_ADVANCED_CRON,
  deriveCronPreset,
  parseAdvancedCronExpression,
  type AdvancedCronValues,
} from "@/features/schedules/components/schedule-cron-model"
import { formatCronExpression } from "@/features/schedules/format"

export function ScheduleCronFields({
  cronExpression,
  error,
  setField,
}: {
  cronExpression: string
  error: string | undefined
  setField: ScheduleFormFieldSetter
}) {
  const selectedPreset = deriveCronPreset(cronExpression)
  const advancedValues = parseAdvancedCronExpression(cronExpression) ?? DEFAULT_ADVANCED_CRON
  const showAdvancedBuilder = selectedPreset === "advanced"

  function handlePresetChange(value: string | null) {
    if (!value) {
      return
    }

    if (value === "advanced") {
      const nextValues = parseAdvancedCronExpression(cronExpression) ?? DEFAULT_ADVANCED_CRON
      updateAdvancedCron(nextValues)
      return
    }

    if (value !== "custom") {
      setField("cronExpression", value)
    }
  }

  function updateAdvancedCron(nextValues: AdvancedCronValues) {
    setField(
      "cronExpression",
      buildAdvancedCron(nextValues.days, nextValues.hour, nextValues.minute)
    )
  }

  return (
    <div className="grid gap-4">
      <Field data-invalid={error ? true : undefined}>
        <FieldLabel htmlFor="schedule-cron-preset">Schedule pattern</FieldLabel>
        <Select onValueChange={handlePresetChange} value={selectedPreset}>
          <SelectTrigger
            aria-invalid={error ? true : undefined}
            className="w-full"
            id="schedule-cron-preset"
          >
            <SelectValue />
          </SelectTrigger>
          <SelectContent align="start">
            <SelectGroup>
              <SelectLabel>Common patterns</SelectLabel>
              {CRON_PRESETS.map((preset) => (
                <SelectItem key={preset.value} label={preset.label} value={preset.value}>
                  <span className="flex min-w-0 flex-col">
                    <span className="truncate">{preset.label}</span>
                    <span className="text-muted-foreground truncate text-xs">
                      {preset.description}
                    </span>
                  </span>
                </SelectItem>
              ))}
              <SelectItem label="Custom days and time" value="advanced">
                <span className="flex min-w-0 flex-col">
                  <span>Custom days and time</span>
                  <span className="text-muted-foreground truncate text-xs">
                    Pick weekdays, hour, and minute
                  </span>
                </span>
              </SelectItem>
              {selectedPreset === "custom" ? (
                <SelectItem label={formatCronExpression(cronExpression)} value="custom">
                  <span className="flex min-w-0 flex-col">
                    <span>Saved custom schedule</span>
                    <span className="text-muted-foreground truncate text-xs">
                      {formatCronExpression(cronExpression)}
                    </span>
                  </span>
                </SelectItem>
              ) : null}
            </SelectGroup>
          </SelectContent>
        </Select>
        <FieldDescription>{formatCronExpression(cronExpression)}</FieldDescription>
        <FieldError>{error}</FieldError>
      </Field>

      {showAdvancedBuilder ? (
        <ScheduleCronAdvancedBuilder onChange={updateAdvancedCron} value={advancedValues} />
      ) : null}
    </div>
  )
}
