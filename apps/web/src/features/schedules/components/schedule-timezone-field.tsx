// apps/web/src/features/schedules/components/schedule-timezone-field.tsx

import { Field, FieldError, FieldLabel } from "@/components/ui/field"
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

const TIME_ZONE_OPTIONS = buildTimeZoneOptions()

export function ScheduleTimezoneField({
  error,
  setField,
  timezone,
}: {
  error: string | undefined
  setField: ScheduleFormFieldSetter
  timezone: string
}) {
  return (
    <div className="grid gap-4 md:grid-cols-2">
      <Field data-invalid={error ? true : undefined}>
        <FieldLabel htmlFor="schedule-timezone">Timezone</FieldLabel>
        <Select
          onValueChange={(value) => {
            if (value !== null) {
              setField("timezone", value)
            }
          }}
          value={timezone}
        >
          <SelectTrigger
            aria-invalid={error ? true : undefined}
            className="w-full"
            id="schedule-timezone"
          >
            <SelectValue />
          </SelectTrigger>
          <SelectContent align="start">
            <SelectGroup>
              <SelectLabel>Timezones</SelectLabel>
              {TIME_ZONE_OPTIONS.map((timezoneOption) => (
                <SelectItem key={timezoneOption} value={timezoneOption}>
                  {timezoneOption}
                </SelectItem>
              ))}
            </SelectGroup>
          </SelectContent>
        </Select>
        <FieldError>{error}</FieldError>
      </Field>
    </div>
  )
}

function buildTimeZoneOptions() {
  const supportedValues = Intl.supportedValuesOf("timeZone")
  return ["UTC", ...supportedValues.filter((value) => value !== "UTC")]
}
