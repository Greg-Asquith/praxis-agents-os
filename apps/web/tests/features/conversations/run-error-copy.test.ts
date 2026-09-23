import { describe, expect, it } from "vitest"

import {
  approvalExpiryOutcome,
  approvalConflictMessage,
  conversationApprovalExpiryOutcome,
  conversationRunInterruptionOutcome,
  runInterruptionOutcome,
  runFailureOutcome,
  formatStreamError,
  tokenBudgetMessage,
} from "@/features/conversations/run-error-copy"
import { ApiError } from "@/lib/api/errors"
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

describe("token budget failures", () => {
  const completion = {
    tripped_budget: { kind: "total_tokens", limit: 1000000, scope: "inherited" },
    observed_total_tokens: 1100000,
    requests: 12,
  }
  const message =
    "This run stopped after counting 1,100,000 tokens across 12 requests; the limit for this run is 1,000,000. " +
    "Start a new conversation or shorten the context to continue."

  it("rebuilds the persisted failure after reload and preserves active-run precedence", () => {
    const run = {
      ...failedRun("usage_limit_exceeded"),
      outcome: "budget_exhausted" as const,
      completion_json: completion,
      error_message: "Old copy",
    }
    expect(conversationRunInterruptionOutcome(null, run)).toMatchObject({
      kind: "budget_exhausted",
      title: "Run limit reached",
      message,
    })
    expect(conversationRunInterruptionOutcome({ ...run, status: "running" }, run)).toBeNull()
  })

  it("formats singular requests and zero limits", () => {
    expect(tokenBudgetMessage({ ...completion, requests: 1 })).toContain("across 1 request;")
    expect(
      tokenBudgetMessage({ ...completion, tripped_budget: { kind: "total_tokens", limit: 0 } })
    ).toContain("limit for this run is 0.")
  })

  it.each([null, "12", -1, 1.5, Number.MAX_SAFE_INTEGER + 1, Infinity, true])(
    "rejects invalid retained counts: %s",
    (value) => {
      expect(tokenBudgetMessage({ ...completion, observed_total_tokens: value })).toBeNull()
      expect(tokenBudgetMessage({ ...completion, requests: value })).toBeNull()
      expect(
        tokenBudgetMessage({
          ...completion,
          tripped_budget: { kind: "total_tokens", limit: value },
        })
      ).toBeNull()
    }
  )

  it("keeps legacy failures readable without inventing observed usage", () => {
    const run = {
      ...failedRun("usage_limit_exceeded"),
      outcome: "budget_exhausted" as const,
      completion_json: { tripped_budget: { kind: "total_tokens", limit: 1000 } },
      error_message: "Saved limit message",
    }
    expect(tokenBudgetMessage(run.completion_json)).toBeNull()
    expect(runInterruptionOutcome(run)?.message).toBe("Saved limit message")
    expect(
      tokenBudgetMessage({ ...completion, tripped_budget: { kind: "requests", limit: 20 } })
    ).toBeNull()
  })
})

describe("root continuation recovery", () => {
  it("retains action evidence after cancellation without changing the stopped outcome", () => {
    const run = failedRun("run_cancelled")
    run.status = "cancelled"
    run.outcome = "cancelled"
    run.completion_json = {
      recovery: {
        actions: [
          {
            owner_run_id: "root",
            tool_call_id: "write",
            tool_name: "write_file",
            status: "uncertain",
          },
        ],
      },
    }
    expect(runInterruptionOutcome(run)).toMatchObject({
      kind: "run_recovery",
      title: "Stopped actions need review",
      uncertainActions: [{ id: "root:write", toolName: "write_file" }],
    })
    run.completion_json = null
    expect(runInterruptionOutcome(run)).toBeNull()
  })
  it("separates completed and uncertain actions and retains safe child links", () => {
    const run = failedRun("agent_run_resume_requires_recovery")
    const child = "11111111-1111-4111-8111-111111111111"
    run.completion_json = {
      recovery: {
        actions: [
          {
            owner_run_id: "child-a",
            tool_call_id: "same",
            tool_name: "write_file",
            status: "completed",
          },
          {
            owner_run_id: "child-b",
            tool_call_id: "same",
            tool_name: "send_email",
            status: "uncertain",
          },
          { owner_run_id: "child-c", tool_call_id: "same", tool_name: "hidden", status: "unknown" },
        ],
        children: [{ conversation_id: child }, { conversation_id: "javascript:alert(1)" }],
        truncated: true,
      },
    }
    const outcome = runInterruptionOutcome(run)
    expect(outcome?.kind).toBe("run_recovery")
    expect(outcome?.completedActions).toEqual([{ id: "child-a:same", toolName: "write_file" }])
    expect(outcome?.uncertainActions).toEqual([{ id: "child-b:same", toolName: "send_email" }])
    expect(outcome?.childConversations).toEqual([child])
    expect(outcome?.actionsTruncated).toBe(true)
  })
  it("bounds evidence and tolerates malformed saved recovery data", () => {
    const run = failedRun("agent_run_resume_requires_recovery")
    run.completion_json = { recovery: "invalid" }
    expect(runInterruptionOutcome(run)?.completedActions).toEqual([])
    run.completion_json = {
      recovery: {
        actions: Array.from({ length: 30 }, (_, index) => ({
          owner_run_id: "root",
          tool_call_id: String(index),
          tool_name: "write_file",
          status: "uncertain",
        })),
      },
    }
    expect(runInterruptionOutcome(run)?.uncertainActions).toHaveLength(25)
    expect(runInterruptionOutcome(run)?.actionsTruncated).toBe(true)
  })
})

describe("approval reservation conflicts", () => {
  it.each([
    ["approval_already_reserved", "Your decisions were already accepted."],
    ["approval_decisions_conflict", "Your latest changes were not applied."],
  ])("distinguishes %s without asking for another submission", (code, message) => {
    const error = new ApiError({ status: 409, message: "Conflict", problem: { code } })
    expect(approvalConflictMessage(error)).toContain(message)
  })
})

describe("historical run failure copy", () => {
  it.each(["provider_error", "model_provider_not_configured", "timeout", "future_error"])(
    "uses the live error copy for %s",
    (code) => {
      const run = failedRun(code)
      run.error_message = "The model could not finish this run."
      expect(runFailureOutcome(run)?.message).toBe(
        formatStreamError({ code, message: run.error_message })
      )
    }
  )

  it("gives an explicit fallback when no reason was saved", () => {
    expect(runFailureOutcome({ ...failedRun("unknown"), error_message: null })?.message).toBe(
      "This run stopped before it finished. Send a new message to try again."
    )
  })
})
