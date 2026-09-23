import { createElement } from "react"
import { renderToStaticMarkup } from "react-dom/server"
import { describe, expect, it, vi } from "vitest"

import { MessageList } from "@/features/conversations/components/message-list"
import { projectConversationTimeline } from "@/features/conversations/message-parts/timeline"
import { tokenBudgetMessage } from "@/features/conversations/run-error-copy"

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
