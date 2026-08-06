import { describe, expect, it } from "vitest"

import {
  approvalExpiryOutcome,
  conversationApprovalExpiryOutcome,
} from "@/features/conversations/run-error-copy"
import type { AgentRun } from "@/features/conversations/types"

function failedRun(errorCode: string): AgentRun {
  return {
    id: "run-1",
    conversation_id: "conversation-1",
    agent_id: "agent-1",
    workspace_id: "workspace-1",
    user_id: "user-1",
    parent_run_id: null,
    delegation_depth: 0,
    trigger: "interactive",
    status: "failed",
    model_name: null,
    started_at: null,
    completed_at: null,
    failed_at: "2026-08-04T12:00:00Z",
    lease_expires_at: null,
    error_code: errorCode,
    error_message: "This approval expired after 7 days, so the action wasn't taken.",
    outcome: "blocked",
    completion_json: { error_code: errorCode },
    created_at: "2026-07-28T12:00:00Z",
    updated_at: "2026-08-04T12:00:00Z",
  }
}

describe("approvalExpiryOutcome", () => {
  it("uses plain outcome language for expired approvals", () => {
    expect(approvalExpiryOutcome(failedRun("approval_expired"))).toBe(
      "This approval expired after 7 days, so the action wasn't taken."
    )
  })

  it("does not replace unrelated run failures", () => {
    expect(approvalExpiryOutcome(failedRun("provider_error"))).toBeNull()
  })

  it("never lets an older expiry outcome replace an active stream", () => {
    const activeRun = { ...failedRun("provider_error"), id: "run-2", status: "running" as const }

    expect(conversationApprovalExpiryOutcome(activeRun, failedRun("approval_expired"))).toBeNull()
  })
})
