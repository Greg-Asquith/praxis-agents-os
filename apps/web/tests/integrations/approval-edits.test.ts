// apps/web/tests/integrations/approval-edits.test.ts

import { describe, expect, it, vi } from "vitest"

import { editApprovalFields } from "@/integrations/approval-edits"

describe("editApprovalFields", () => {
  it("applies several edits in one decision change", () => {
    const onDecisionChange = vi.fn()
    const controls = {
      decision: { decision: "pending" as const, edits: { name: "Kept" }, message: "" as const },
      error: null,
      onDecisionChange,
      onRetry: vi.fn(),
      pendingCount: 1,
      submitting: false,
    }
    editApprovalFields(controls, false, { objective: "traffic", bid_strategy: "highest_volume" })
    editApprovalFields(controls, true, { name: "Ignored" })

    expect(onDecisionChange).toHaveBeenCalledTimes(1)
    expect(onDecisionChange).toHaveBeenCalledWith({
      decision: "pending",
      edits: { name: "Kept", objective: "traffic", bid_strategy: "highest_volume" },
      message: "",
    })
  })
})
