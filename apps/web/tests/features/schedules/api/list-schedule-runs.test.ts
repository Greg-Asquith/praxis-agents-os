import { describe, expect, it } from "vitest"

import {
  SCHEDULE_RUNS_REFETCH_INTERVAL_MS,
  scheduleRunsQueryOptions,
} from "@/features/schedules/api/list-schedule-runs"

describe("scheduleRunsQueryOptions", () => {
  it("refreshes visible run history every 30 seconds", () => {
    const options = scheduleRunsQueryOptions("schedule-1", { limit: 100 }, true)

    expect(options.enabled).toBe(true)
    expect(options.refetchInterval).toBe(SCHEDULE_RUNS_REFETCH_INTERVAL_MS)
    expect(SCHEDULE_RUNS_REFETCH_INTERVAL_MS).toBe(30_000)
  })

  it("does not fetch while the run-history panel is hidden", () => {
    const options = scheduleRunsQueryOptions("schedule-1", { limit: 100 }, false)

    expect(options.enabled).toBe(false)
  })
})
