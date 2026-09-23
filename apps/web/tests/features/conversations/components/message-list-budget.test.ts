import { createElement } from "react"
import { renderToStaticMarkup } from "react-dom/server"
import { describe, expect, it, vi } from "vitest"

import { MessageList } from "@/features/conversations/components/message-list"
import { projectConversationTimeline } from "@/features/conversations/message-parts/timeline"
import { tokenBudgetMessage, runInterruptionOutcome } from "@/features/conversations/run-error-copy"

vi.mock("@/features/conversations/api/review-approval", () => ({
  useReviewApprovalMutation: () => ({ mutateAsync: vi.fn() }),
}))
vi.mock("@/features/tools/use-tool-labels", () => ({ useToolLabels: () => (name: string) => name }))
vi.mock("@/features/tools/use-tool-presentations", () => ({
  useToolPresentations: () => () => null,
}))

describe("MessageList budget failure", () => {
  it("shows the complete failure after an empty transcript reload and avoids duplicate stream copy", () => {
    const message = tokenBudgetMessage({
      tripped_budget: { kind: "total_tokens", limit: 1000000 },
      observed_total_tokens: 1100000,
      requests: 12,
    })
    if (message === null) throw new Error("Expected token budget message")
    const timeline = projectConversationTimeline({
      conversationId: "chat",
      assistantAgentId: "agent",
      messages: [],
      approvals: [],
      pendingDelegations: [],
      pendingUserMessages: [],
      pendingWorkflow: null,
      transcriptRun: null,
      stream: {
        approvals: [],
        conversationId: null,
        isStreaming: false,
        messages: [],
        runId: null,
        toolCalls: [],
      },
    })
    const html = renderToStaticMarkup(
      createElement(MessageList, {
        conversationId: "chat",
        timeline,
        assistantAgentMetadata: null,
        assistantLabel: "Agent",
        approvalError: null,
        isApprovalLoading: false,
        isApprovalSubmitting: false,
        onApprovalSubmit: () => Promise.resolve(),
        streamError: message,
        runInterruption: {
          kind: "budget_exhausted",
          title: "Run limit reached",
          message,
          completedActions: [],
          actionsTruncated: false,
        },
      })
    )
    expect(html).toContain("Run limit reached")
    expect(html).toContain(message)
    expect(html.match(/This run stopped/g)).toHaveLength(1)
    expect(html).not.toContain("No messages yet")
  })
})

const createdAt = "2026-09-23T10:00:00Z"

it.each([false, true])(
  "renders the run-boundary reason once with a visible stream error: %s",
  (live) => {
    const reason = "The model could not finish this run."
    const run = {
      id: "failed",
      conversation_id: "chat",
      agent_id: "agent",
      workspace_id: "workspace",
      user_id: "user",
      parent_run_id: null,
      delegation_depth: 0,
      trigger: "interactive" as const,
      status: "failed" as const,
      outcome: "error" as const,
      model_name: null,
      started_at: createdAt,
      completed_at: null,
      failed_at: createdAt,
      lease_expires_at: null,
      error_code: "provider_error",
      error_message: reason,
      completion_json: null,
      created_at: createdAt,
      updated_at: createdAt,
    }
    const timeline = projectConversationTimeline({
      conversationId: "chat",
      assistantAgentId: "agent",
      runs: { failed: run },
      visibleRunNoticeIds: live ? [run.id] : [],
      messages: [
        {
          id: "prompt",
          conversation_id: "chat",
          role: "user",
          sequence: 1,
          parts: { parts: [{ part_kind: "user-prompt", content: "Start the report" }] },
          metadata: { agent_run_id: run.id },
          client_message_id: null,
          tool_name: null,
          error: null,
          created_at: createdAt,
          updated_at: createdAt,
        },
        {
          id: "later",
          conversation_id: "chat",
          role: "user",
          sequence: 2,
          parts: { parts: [{ part_kind: "user-prompt", content: "A later instruction" }] },
          metadata: { agent_run_id: "later-run" },
          client_message_id: null,
          tool_name: null,
          error: null,
          created_at: createdAt,
          updated_at: createdAt,
        },
      ],
      approvals: [],
      pendingDelegations: [],
      pendingUserMessages: [],
      pendingWorkflow: null,
      transcriptRun: null,
      stream: {
        approvals: [],
        conversationId: null,
        isStreaming: false,
        messages: [],
        runId: null,
        toolCalls: [],
      },
    })
    const html = renderToStaticMarkup(
      createElement(MessageList, {
        conversationId: "chat",
        timeline,
        assistantAgentMetadata: null,
        assistantLabel: "Agent",
        approvalError: null,
        isApprovalLoading: false,
        isApprovalSubmitting: false,
        onApprovalSubmit: () => Promise.resolve(),
        streamError: live ? reason : null,
        runInterruption: runInterruptionOutcome(run),
      })
    )
    expect(html.match(/The model could not finish this run/g)).toHaveLength(1)
    if (!live) {
      expect(html.indexOf(reason)).toBeGreaterThan(html.indexOf("Start the report"))
      expect(html.indexOf(reason)).toBeLessThan(html.indexOf("A later instruction"))
    }
  }
)
