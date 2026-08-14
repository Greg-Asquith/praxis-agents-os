import { describe, expect, it } from "vitest"

import {
  approvalExpiryOutcome,
  conversationApprovalExpiryOutcome,
  runInterruptionOutcome,
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

  it("promotes code mode recovery with bounded completed actions", () => {
    const run = failedRun("code_mode_resume_requires_recovery")
    run.error_message = null
    run.completion_json = {
      error_code: "code_mode_resume_requires_recovery",
      executed_effects: [
        { tool_name: "update_campaign_status", args_sha256: "hidden" },
        { tool_name: "write_file", args_sha256: "hidden" },
      ],
    }

    expect(runInterruptionOutcome(run)).toEqual({
      kind: "code_mode_recovery",
      title: "Workflow Needs Review",
      message:
        "This workflow couldn't resume safely after completing an action. Review what completed, then send a new instruction to continue.",
      completedActions: [
        { id: "update_campaign_status:1", toolName: "update_campaign_status" },
        { id: "write_file:1", toolName: "write_file" },
      ],
      actionsTruncated: false,
    })
  })

  it("degrades cleanly for malformed, legacy, and truncated evidence", () => {
    const malformed = failedRun("code_mode_resume_requires_recovery")
    malformed.completion_json = { executed_effects: "not-a-list" }
    expect(runInterruptionOutcome(malformed)?.completedActions).toEqual([])

    const truncated = failedRun("code_mode_resume_requires_recovery")
    truncated.completion_json = {
      executed_effects: Array.from({ length: 30 }, (_, index) => ({
        tool_name: `tool_${String(index)}`,
      })),
    }
    expect(runInterruptionOutcome(truncated)?.completedActions).toHaveLength(25)
    expect(runInterruptionOutcome(truncated)?.actionsTruncated).toBe(true)
  })
})
