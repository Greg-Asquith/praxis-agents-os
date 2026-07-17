import { describe, expect, it } from "vitest"

import {
  DEFAULT_CRON_EXPRESSION,
  buildSchedulePayload,
  buildSchedulePreviewPayload,
  initialScheduleFormState,
  isScheduleFormDirty,
  validateScheduleFormState,
  type ScheduleFormState,
} from "@/features/schedules/components/schedule-form-model"
import type { AgentSchedule } from "@/features/schedules/types"

function validState(overrides: Partial<ScheduleFormState> = {}): ScheduleFormState {
  return {
    agentId: "agent-1",
    cronExpression: DEFAULT_CRON_EXPRESSION,
    defaultPrompt: "  Run the launch report.  ",
    executionParams: null,
    externalWritesAllowed: false,
    intervalMinutes: "60",
    isActive: true,
    name: "  Weekly launch report  ",
    runOnceAt: "",
    scheduleType: "cron",
    timezone: "UTC",
    ...overrides,
  }
}

const schedule: AgentSchedule = {
  id: "schedule-1",
  agent_id: "agent-1",
  user_id: "user-1",
  workspace_id: "workspace-1",
  name: "One-time report",
  schedule_type: "once",
  cron_expression: null,
  interval_minutes: null,
  run_once_at: "2027-07-01T08:30:00.000Z",
  timezone: "Europe/London",
  default_prompt: "Run once.",
  execution_params: null,
  is_active: false,
  last_run_at: null,
  next_run_at: null,
  created_at: "2026-07-07T10:00:00.000Z",
  updated_at: "2026-07-07T10:00:00.000Z",
  health: "healthy",
  latest_run: null,
}

describe("initialScheduleFormState", () => {
  it("uses defaults for a new schedule", () => {
    expect(initialScheduleFormState(null)).toEqual({
      agentId: "",
      cronExpression: DEFAULT_CRON_EXPRESSION,
      defaultPrompt: "",
      executionParams: null,
      externalWritesAllowed: false,
      intervalMinutes: "60",
      isActive: true,
      name: "",
      runOnceAt: "",
      scheduleType: "cron",
      timezone: "UTC",
    })
  })

  it("round-trips an existing once schedule into local wall time", () => {
    expect(initialScheduleFormState(schedule)).toEqual({
      agentId: "agent-1",
      cronExpression: DEFAULT_CRON_EXPRESSION,
      defaultPrompt: "Run once.",
      executionParams: null,
      externalWritesAllowed: false,
      intervalMinutes: "60",
      isActive: false,
      name: "One-time report",
      runOnceAt: "2027-07-01T09:30",
      scheduleType: "once",
      timezone: "Europe/London",
    })
  })
})

describe("validateScheduleFormState", () => {
  it("returns entries for missing required fields", () => {
    expect(
      validateScheduleFormState(
        validState({
          agentId: "",
          cronExpression: "",
          defaultPrompt: " ",
          name: " ",
          timezone: "",
        })
      )
    ).toEqual([
      {
        fieldId: "schedule-name",
        label: "Name",
        message: "Name is required.",
      },
      {
        fieldId: "schedule-agent",
        label: "Agent",
        message: "Choose the agent this schedule should run.",
      },
      {
        fieldId: "schedule-prompt",
        label: "Prompt",
        message: "Prompt is required.",
      },
      {
        fieldId: "schedule-timezone",
        label: "Timezone",
        message: "Timezone is required.",
      },
      {
        fieldId: "schedule-cron",
        label: "Cron expression",
        message: "Cron expression is required.",
      },
    ])
  })

  it("rejects non-integer and sub-minute intervals", () => {
    expect(
      validateScheduleFormState(validState({ intervalMinutes: "1.5", scheduleType: "interval" }))
    ).toContainEqual({
      fieldId: "schedule-interval",
      label: "Interval",
      message: "Interval must be a whole number of at least 1 minute.",
    })
    expect(
      validateScheduleFormState(validState({ intervalMinutes: "0", scheduleType: "interval" }))
    ).toContainEqual({
      fieldId: "schedule-interval",
      label: "Interval",
      message: "Interval must be a whole number of at least 1 minute.",
    })
  })

  it("accepts valid state", () => {
    expect(validateScheduleFormState(validState())).toEqual([])
  })
})

describe("buildSchedulePayload", () => {
  it("builds create and edit cron payloads", () => {
    expect(buildSchedulePayload(validState(), "create")).toEqual({
      agent_id: "agent-1",
      name: "Weekly launch report",
      schedule_type: "cron",
      cron_expression: DEFAULT_CRON_EXPRESSION,
      interval_minutes: null,
      run_once_at: null,
      timezone: "UTC",
      default_prompt: "Run the launch report.",
      execution_params: null,
      is_active: true,
    })
    expect(buildSchedulePayload(validState({ cronExpression: "*/15 * * * *" }), "edit")).toEqual({
      name: "Weekly launch report",
      schedule_type: "cron",
      cron_expression: "*/15 * * * *",
      interval_minutes: null,
      run_once_at: null,
      timezone: "UTC",
      default_prompt: "Run the launch report.",
      execution_params: null,
      is_active: true,
    })
  })

  it("builds an explicit external-write grant when enabled", () => {
    expect(
      buildSchedulePayload(validState({ externalWritesAllowed: true }), "create")
    ).toMatchObject({
      execution_params: { envelope: { side_effect_policy: "allow" } },
    })
  })

  it("removes a revoked grant while preserving unrelated execution params", () => {
    const state = validState({
      executionParams: {
        envelope: {
          requested_by: "ops",
          side_effect_policy: "allow",
        },
        temperature: 0,
      },
      externalWritesAllowed: false,
    })

    expect(buildSchedulePayload(state, "edit")).toMatchObject({
      execution_params: {
        envelope: {
          requested_by: "ops",
        },
        temperature: 0,
      },
    })
  })

  it("preserves an existing explicit approval policy during ordinary edits", () => {
    const state = validState({
      executionParams: {
        envelope: { side_effect_policy: "require_approval" },
      },
      externalWritesAllowed: false,
    })

    expect(buildSchedulePayload(state, "edit")).toMatchObject({
      execution_params: {
        envelope: { side_effect_policy: "require_approval" },
      },
    })
  })

  it("serializes a Europe/London wall time during daylight saving time", () => {
    expect(
      buildSchedulePayload(
        validState({
          runOnceAt: "2027-07-01T09:30",
          scheduleType: "once",
          timezone: "Europe/London",
        }),
        "create"
      )
    ).toMatchObject({
      run_once_at: "2027-07-01T08:30:00.000Z",
      schedule_type: "once",
      timezone: "Europe/London",
    })
  })

  it("rejects nonexistent spring-forward wall time and invalid datetime strings", () => {
    expect(
      buildSchedulePayload(
        validState({
          runOnceAt: "2027-03-28T01:30",
          scheduleType: "once",
          timezone: "Europe/London",
        }),
        "create"
      )
    ).toBe("Run once time is invalid.")
    expect(
      buildSchedulePayload(
        validState({
          runOnceAt: "not-a-date",
          scheduleType: "once",
          timezone: "Europe/London",
        }),
        "create"
      )
    ).toBe("Run once time is invalid.")
  })

  it("returns validation strings for invalid interval payloads", () => {
    expect(
      buildSchedulePayload(validState({ intervalMinutes: "abc", scheduleType: "interval" }), "edit")
    ).toBe("Interval must be a whole number of at least 1 minute.")
  })
})

describe("buildSchedulePreviewPayload", () => {
  it("adds a default preview count to valid timing state", () => {
    expect(buildSchedulePreviewPayload(validState({ scheduleType: "interval" }))).toEqual({
      schedule_type: "interval",
      cron_expression: null,
      interval_minutes: 60,
      run_once_at: null,
      timezone: "UTC",
      preview_count: 5,
    })
  })

  it("returns null when timing state is invalid", () => {
    expect(
      buildSchedulePreviewPayload(validState({ intervalMinutes: "", scheduleType: "interval" }))
    ).toBeNull()
  })
})

describe("isScheduleFormDirty", () => {
  it("tracks field-level changes", () => {
    const initial = initialScheduleFormState(schedule)

    expect(isScheduleFormDirty(initial, initial)).toBe(false)
    expect(isScheduleFormDirty({ ...initial, timezone: "UTC" }, initial)).toBe(true)
    expect(isScheduleFormDirty({ ...initial, name: "Renamed report" }, initial)).toBe(true)
  })
})
