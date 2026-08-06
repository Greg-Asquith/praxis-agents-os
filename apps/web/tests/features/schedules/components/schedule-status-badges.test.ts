import { createElement } from "react"
import { renderToStaticMarkup } from "react-dom/server"
import { describe, expect, it } from "vitest"

import { ScheduleRunStatusBadge } from "@/features/schedules/components/schedule-status-badges"
import type { RunOutcome } from "@/features/conversations/types"

const OUTCOME_LABELS = {
  success: "Succeeded",
  gate_failed: "Checks failed",
  budget_exhausted: "Token limit reached",
  blocked: "Blocked",
  error: "Failed",
  cancelled: "Cancelled",
} satisfies Record<RunOutcome, string>

describe("ScheduleRunStatusBadge", () => {
  it.each(Object.entries(OUTCOME_LABELS) as [RunOutcome, string][])(
    "renders the %s outcome in operator language",
    (outcome, label) => {
      const markup = renderToStaticMarkup(
        createElement(ScheduleRunStatusBadge, { outcome, status: "completed" })
      )

      expect(markup).toContain(label)
    }
  )

  it("keeps non-terminal schedule status language before an outcome exists", () => {
    const markup = renderToStaticMarkup(
      createElement(ScheduleRunStatusBadge, { outcome: null, status: "awaiting_approval" })
    )

    expect(markup).toContain("Awaiting approval")
  })

  it("surfaces the precise tripped schedule budget", () => {
    const markup = renderToStaticMarkup(
      createElement(ScheduleRunStatusBadge, {
        completionJson: {
          error_code: "usage_limit_exceeded",
          tripped_budget: { kind: "total_tokens", limit: 12000 },
        },
        outcome: "budget_exhausted",
        status: "terminal_failed",
      })
    )

    expect(markup).toContain("Token budget reached (12,000)")
  })
})
