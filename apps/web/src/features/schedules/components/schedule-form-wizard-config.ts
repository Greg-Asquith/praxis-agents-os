// apps/web/src/features/schedules/components/schedule-form-wizard-config.ts

import type { FormWizardStep } from "@/components/forms/form-wizard"
import type { FormValidationEntry } from "@/lib/forms"

export type ScheduleWizardStepId = "run" | "timing" | "review"

const SCHEDULE_FORM_STEPS = [
  { id: "run", title: "What should run?" },
  { id: "timing", title: "When should it run?" },
  { id: "review", title: "Review and options" },
] as const satisfies readonly [
  FormWizardStep<ScheduleWizardStepId>,
  ...FormWizardStep<ScheduleWizardStepId>[],
]

export const SCHEDULE_CREATE_STEPS = SCHEDULE_FORM_STEPS
export const SCHEDULE_EDIT_STEPS = SCHEDULE_FORM_STEPS

const SCHEDULE_STEP_FIELDS: Record<ScheduleWizardStepId, ReadonlySet<string>> = {
  review: new Set(),
  run: new Set(["schedule-name", "schedule-agent", "schedule-prompt"]),
  timing: new Set(["schedule-timezone", "schedule-cron", "schedule-interval", "schedule-once"]),
}

export function scheduleValidationEntriesForStep(
  entries: readonly FormValidationEntry[],
  stepId: ScheduleWizardStepId
) {
  const stepFields = SCHEDULE_STEP_FIELDS[stepId]
  return entries.filter((entry) => stepFields.has(entry.fieldId))
}

export function stepForScheduleField(fieldId: string | undefined): ScheduleWizardStepId {
  if (fieldId && SCHEDULE_STEP_FIELDS.timing.has(fieldId)) {
    return "timing"
  }
  return "run"
}
