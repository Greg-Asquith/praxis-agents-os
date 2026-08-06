import { describe, expect, it } from "vitest"

import {
  APPROVAL_EXPIRY_HEAL_POLL_INTERVAL_MS,
  CONVERSATION_HEAL_POLL_INTERVAL_MS,
  conversationActiveRunRefetchInterval,
  conversationHealPollInterval,
} from "@/features/conversations/conversation-heal-polling"
import type { AgentRun, ConversationActiveRunResponse } from "@/features/conversations/types"

function activeRunResponse(
  status: AgentRun["status"],
  approvalExpiresAt: string | null = null
): ConversationActiveRunResponse {
  return {
    active_run: {
      id: "run-1",
      conversation_id: "conversation-1",
      agent_id: "agent-1",
      workspace_id: "workspace-1",
      user_id: "user-1",
      parent_run_id: null,
      delegation_depth: 0,
      trigger: "interactive",
      status,
      model_name: null,
      started_at: null,
      completed_at: null,
      failed_at: null,
      lease_expires_at: null,
      error_code: null,
      error_message: null,
      outcome: null,
      completion_json: null,
      created_at: "2026-08-04T12:00:00Z",
      updated_at: "2026-08-04T12:00:00Z",
    },
    latest_run: null,
    approval_expires_at: approvalExpiresAt,
  }
}

describe("conversation heal polling", () => {
  it.each(["pending", "running"] as const)("polls while a run is %s", (status) => {
    expect(conversationHealPollInterval(status, null)).toBe(CONVERSATION_HEAL_POLL_INTERVAL_MS)
  })

  it.each([null, "awaiting_approval", "completed", "failed", "cancelled"] as const)(
    "stops when the run status is %s",
    (status) => {
      expect(conversationHealPollInterval(status, null)).toBe(false)
    }
  )

  it("stops after the query layer exhausts retries", () => {
    expect(conversationHealPollInterval("running", new Error("API unavailable"))).toBe(false)
  })

  it("waits until the approval deadline instead of polling throughout the wait", () => {
    const now = Date.parse("2026-08-04T12:00:00Z")
    const expiresAt = "2026-08-11T12:00:00Z"

    expect(
      conversationActiveRunRefetchInterval(
        activeRunResponse("awaiting_approval", expiresAt),
        null,
        now
      )
    ).toBe(7 * 24 * 60 * 60 * 1_000 + APPROVAL_EXPIRY_HEAL_POLL_INTERVAL_MS)
  })

  it("heals shortly after an approval deadline passes", () => {
    expect(
      conversationActiveRunRefetchInterval(
        activeRunResponse("awaiting_approval", "2026-08-04T11:59:59Z"),
        null,
        Date.parse("2026-08-04T12:00:00Z")
      )
    ).toBe(APPROVAL_EXPIRY_HEAL_POLL_INTERVAL_MS)
  })

  it("does not poll indefinitely when expiry is disabled", () => {
    expect(conversationActiveRunRefetchInterval(activeRunResponse("awaiting_approval"), null)).toBe(
      false
    )
  })
})
