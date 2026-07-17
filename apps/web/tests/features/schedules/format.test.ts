import { describe, expect, it } from "vitest"

import { formatScheduleCadence, scheduleTitle } from "@/features/schedules/format"
import type { AgentSchedule } from "@/features/schedules/types"

function schedule(overrides: Partial<AgentSchedule> = {}): AgentSchedule {
  return {
    id: "schedule-1",
    agent_id: "agent-1",
    user_id: "user-1",
    workspace_id: "workspace-1",
    name: "Weekly account review",
    schedule_type: "interval",
    cron_expression: null,
    interval_minutes: 60,
    run_once_at: null,
    timezone: "UTC",
    default_prompt: "Review the accounts.",
    execution_params: null,
    is_active: true,
    last_run_at: null,
    next_run_at: null,
    created_at: "2026-07-16T10:00:00.000Z",
    updated_at: "2026-07-16T10:00:00.000Z",
    health: "healthy",
    latest_run: null,
    ...overrides,
  }
}

describe("schedule display formatting", () => {
  it("uses the persisted name as the title and keeps cadence separate", () => {
    const value = schedule()

    expect(scheduleTitle(value)).toBe("Weekly account review")
    expect(formatScheduleCadence(value)).toBe("Every 60 min")
  })

  it("labels legacy unnamed rows honestly", () => {
    expect(scheduleTitle(schedule({ name: null }))).toBe("Unnamed schedule")
  })
})
