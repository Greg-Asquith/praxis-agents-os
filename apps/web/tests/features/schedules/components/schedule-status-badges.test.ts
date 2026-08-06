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
})
