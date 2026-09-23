import { createElement } from "react"
import { renderToStaticMarkup } from "react-dom/server"
import { describe, expect, it, vi } from "vitest"

import { ScheduleRunHistory } from "@/features/schedules/components/schedule-run-history"
import { useScheduleRunsQuery } from "@/features/schedules/api/list-schedule-runs"
import type { AgentScheduleRun } from "@/features/schedules/types"

vi.mock("@/features/schedules/api/list-schedule-runs", () => ({ useScheduleRunsQuery: vi.fn() }))

describe("ScheduleRunHistory budget failure", () => {
  it("shows counted usage, requests, ceiling, and recovery advice on desktop and mobile", () => {
    const run: AgentScheduleRun = {
      id: "run",
      schedule_id: "schedule",
      scheduled_for: "2026-09-23T09:00:00Z",
      status: "terminal_failed",
      attempt_count: 1,
      conversation_id: null,
      agent_run_id: "agent-run",
      accepted_at: null,
      completed_at: null,
      failed_at: "2026-09-23T09:01:00Z",
      last_error_code: "usage_limit_exceeded",
      last_error_message: "Old copy",
      outcome: "budget_exhausted",
      completion_json: {
        tripped_budget: { kind: "total_tokens", limit: 1000000 },
        observed_total_tokens: 1100000,
        requests: 12,
      },
      created_at: "2026-09-23T09:00:00Z",
      health: "needs_attention",
    }
    vi.mocked(useScheduleRunsQuery).mockReturnValue({
      data: { items: [run] },
      isPending: false,
      isError: false,
    } as ReturnType<typeof useScheduleRunsQuery>)
    const html = renderToStaticMarkup(
      createElement(ScheduleRunHistory, { enabled: true, scheduleId: "schedule" })
    )
    expect(html.match(/1,100,000 tokens across 12 requests/g)).toHaveLength(2)
    expect(html.match(/the limit for this run is 1,000,000/g)).toHaveLength(2)
    expect(
      html.match(/Start a new conversation or shorten the context to continue\./g)
    ).toHaveLength(2)
    expect(html).not.toContain("Old copy")
    expect(html).not.toContain("usage_limit_exceeded")
  })
})
