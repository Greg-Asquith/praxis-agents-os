import { describe, expect, it } from "vitest"

import {
  SCHEDULE_CREATE_STEPS,
  SCHEDULE_EDIT_STEPS,
  scheduleValidationEntriesForStep,
  stepForScheduleField,
} from "@/features/schedules/components/schedule-form-wizard-config"
import type { FormValidationEntry } from "@/lib/forms"

const validationEntries: FormValidationEntry[] = [
  { fieldId: "schedule-name", label: "Name", message: "Name is required." },
  { fieldId: "schedule-agent", label: "Agent", message: "Choose an agent." },
  { fieldId: "schedule-prompt", label: "Prompt", message: "Prompt is required." },
  { fieldId: "schedule-timezone", label: "Timezone", message: "Timezone is required." },
  { fieldId: "schedule-cron", label: "Cron expression", message: "Cron is required." },
  { fieldId: "schedule-interval", label: "Interval", message: "Interval is required." },
  { fieldId: "schedule-once", label: "Run once at", message: "Run time is required." },
]

describe("schedule wizard configuration", () => {
  it("uses the same exact three-step order for create and edit", () => {
    expect(SCHEDULE_CREATE_STEPS.map((step) => step.id)).toEqual(["run", "timing", "review"])
    expect(SCHEDULE_EDIT_STEPS.map((step) => step.id)).toEqual(["run", "timing", "review"])
  })

  it("partitions every existing validation field without duplicating rules", () => {
    expect(scheduleValidationEntriesForStep(validationEntries, "run")).toEqual(
      validationEntries.slice(0, 3)
    )
    expect(scheduleValidationEntriesForStep(validationEntries, "timing")).toEqual(
      validationEntries.slice(3)
    )
    expect(scheduleValidationEntriesForStep(validationEntries, "review")).toEqual([])
  })

  it("routes final failures to timing or falls back to run", () => {
    expect(stepForScheduleField("schedule-timezone")).toBe("timing")
    expect(stepForScheduleField("schedule-cron")).toBe("timing")
    expect(stepForScheduleField("schedule-interval")).toBe("timing")
    expect(stepForScheduleField("schedule-once")).toBe("timing")
    expect(stepForScheduleField("schedule-name")).toBe("run")
    expect(stepForScheduleField("schedule-agent")).toBe("run")
    expect(stepForScheduleField("unknown-field")).toBe("run")
    expect(stepForScheduleField(undefined)).toBe("run")
  })
})
