import { describe, expect, it } from "vitest"

import {
  DEFAULT_CRON_EXPRESSION,
  type ScheduleFormState,
} from "@/features/schedules/components/schedule-form-model"
import { formatScheduleFormCadence } from "@/features/schedules/components/schedule-form-review-format"

function formState(overrides: Partial<ScheduleFormState> = {}): ScheduleFormState {
  return {
    agentId: "agent-1",
    cronExpression: DEFAULT_CRON_EXPRESSION,
    defaultPrompt: "Run the report.",
    executionParams: null,
    externalWritesAllowed: false,
    intervalMinutes: "60",
    isActive: true,
    name: "Weekly report",
    runOnceAt: "",
    scheduleType: "cron",
    timezone: "UTC",
    ...overrides,
  }
}

describe("formatScheduleFormCadence", () => {
  it("uses the shared recurring wording", () => {
    expect(formatScheduleFormCadence(formState())).toBe("At 09:00 AM, Monday through Friday")
  })

  it("uses the shared interval wording", () => {
    expect(
      formatScheduleFormCadence(formState({ intervalMinutes: "90", scheduleType: "interval" }))
    ).toBe("Every 90 min")
  })

  it("normalizes one-time wall time before using the shared wording", () => {
    expect(
      formatScheduleFormCadence(
        formState({
          runOnceAt: "2027-07-01T09:30",
          scheduleType: "once",
          timezone: "Europe/London",
        })
      )
    ).toBe("Once at Jul 1, 2027, 9:30 AM")
  })
})
