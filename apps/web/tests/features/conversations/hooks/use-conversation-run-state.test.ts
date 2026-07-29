import { describe, expect, it } from "vitest"

import {
  formatStreamError,
  hasPersistedRunResponse,
  shouldRenderConversationStream,
} from "@/features/conversations/hooks/use-conversation-run-state"
import type { ConversationMessage } from "@/features/conversations/types"

function message({
  role,
  runId,
}: {
  role: "assistant" | "user"
  runId: string
}): ConversationMessage {
  return {
    id: `${role}-message`,
    conversation_id: "conversation-1",
    role,
    parts: {},
    metadata: { agent_run_id: runId },
    tool_name: null,
    error: null,
    sequence: role === "user" ? 1 : 2,
    client_message_id: role === "user" ? "client-message-1" : null,
    created_at: "2026-07-17T15:00:00Z",
    updated_at: "2026-07-17T15:00:00Z",
  }
}

describe("conversation stream persistence handoff", () => {
  it("does not treat the eagerly persisted user prompt as the streamed response", () => {
    expect(hasPersistedRunResponse([message({ role: "user", runId: "run-1" })], "run-1")).toBe(
      false
    )
  })

  it("recognizes the persisted assistant response for the streamed run", () => {
    expect(
      hasPersistedRunResponse(
        [message({ role: "user", runId: "run-1" }), message({ role: "assistant", runId: "run-1" })],
        "run-1"
      )
    ).toBe(true)
  })

  it("keeps the settled stream visible until its persisted response is renderable", () => {
    const common = {
      activeRun: null,
      conversationId: "conversation-1",
      streamConversationId: "conversation-1",
      submittingApprovalRunId: null,
    }

    expect(shouldRenderConversationStream({ ...common, hasPersistedStreamResponse: false })).toBe(
      true
    )
    expect(shouldRenderConversationStream({ ...common, hasPersistedStreamResponse: true })).toBe(
      false
    )
  })
})

describe("conversation stream errors", () => {
  it("turns a missing provider key into an actionable local settings hint", () => {
    expect(
      formatStreamError({
        code: "model_provider_not_configured",
        message: "No API key is configured for model provider 'anthropic'.",
      })
    ).toBe(
      "No API key is configured for model provider 'anthropic'. Add the provider's API key " +
        "to .local/targets/local.secrets.env (Docker stack) or apps/api/.env (make dev), " +
        "then restart Praxis."
    )
  })

  it("keeps other stream errors unchanged", () => {
    expect(formatStreamError({ code: "provider_failed", message: "Provider failed." })).toBe(
      "Provider failed."
    )
  })
})
