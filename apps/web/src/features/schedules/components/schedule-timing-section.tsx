// apps/web/src/features/schedules/components/schedule-timing-section.tsx

import { ClockIcon } from "lucide-react"

import { FieldGroup } from "@/components/ui/field"
import type {
  ScheduleFormFieldSetter,
  ScheduleFormState,
} from "@/features/schedules/components/schedule-form-model"
import { ScheduleCadenceField } from "@/features/schedules/components/schedule-cadence-field"
import { ScheduleCronFields } from "@/features/schedules/components/schedule-cron-fields"
import { ScheduleFormSection } from "@/features/schedules/components/schedule-form-section"
import { ScheduleIntervalFields } from "@/features/schedules/components/schedule-interval-fields"
import { ScheduleOnceFields } from "@/features/schedules/components/schedule-once-fields"
import { ScheduleTimezoneField } from "@/features/schedules/components/schedule-timezone-field"

type ScheduleTimingFieldErrors = Record<
  "cron" | "interval" | "once" | "timezone",
  string | undefined
>

export function ScheduleTimingSection({
  fieldErrors,
  setField,
  state,
}: {
  fieldErrors: ScheduleTimingFieldErrors
  setField: ScheduleFormFieldSetter
  state: ScheduleFormState
}) {
  return (
    <ScheduleFormSection
      description="Choose a common cadence or build a custom recurring pattern without technical syntax."
      eyebrow="Cadence"
      icon={<ClockIcon className="size-4" />}
      title="When should it run?"
    >
      <FieldGroup>
        <ScheduleCadenceField setField={setField} state={state} />

        <ScheduleTimezoneField
          error={fieldErrors.timezone}
          setField={setField}
          timezone={state.timezone}
        />

        {state.scheduleType === "cron" ? (
          <ScheduleCronFields
            cronExpression={state.cronExpression}
            error={fieldErrors.cron}
            setField={setField}
          />
        ) : null}

        {state.scheduleType === "interval" ? (
          <ScheduleIntervalFields
            error={fieldErrors.interval}
            intervalMinutes={state.intervalMinutes}
            setField={setField}
          />
        ) : null}

        {state.scheduleType === "once" ? (
          <ScheduleOnceFields
            error={fieldErrors.once}
            runOnceAt={state.runOnceAt}
            setField={setField}
          />
        ) : null}
      </FieldGroup>
    </ScheduleFormSection>
  )
}
