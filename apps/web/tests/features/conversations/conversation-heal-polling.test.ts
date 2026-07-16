import { describe, expect, it } from "vitest"

import {
  CONVERSATION_HEAL_POLL_INTERVAL_MS,
  conversationHealPollInterval,
} from "@/features/conversations/conversation-heal-polling"

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
})
