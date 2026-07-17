import { describe, expect, it } from "vitest"

import { conversationScheduleContext } from "@/features/conversations/format"

describe("conversationScheduleContext", () => {
  it("reads the linked schedule and run time", () => {
    expect(
      conversationScheduleContext({
        schedule: {
          schedule_id: "schedule-1",
          schedule_run_id: "run-1",
          scheduled_for: "2026-07-16T18:30:00Z",
        },
      })
    ).toEqual({
      scheduleId: "schedule-1",
      scheduledFor: "2026-07-16T18:30:00Z",
    })
  })

  it("returns null when schedule metadata is absent", () => {
    expect(conversationScheduleContext(null)).toBeNull()
    expect(conversationScheduleContext({ schedule: "unknown" })).toBeNull()
  })
})
