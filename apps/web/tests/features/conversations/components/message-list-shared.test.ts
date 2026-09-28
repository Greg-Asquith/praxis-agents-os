import { SharedTranscriptContext } from "@/components/tool-ui/tool-conversation-context"
import { createElement } from "react"
import { renderToStaticMarkup } from "react-dom/server"
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { describe, expect, it, vi } from "vitest"

import { MessageList } from "@/features/conversations/components/message-list"
import { ToolCallRow } from "@/features/conversations/components/tool-call-row"
import { projectConversationTimeline } from "@/features/conversations/message-parts/timeline"
import type { ConversationMessage } from "@/features/conversations/types"
import { useInlineApprovals } from "@/features/conversations/hooks/use-inline-approvals"

vi.mock("@/features/conversations/hooks/use-inline-approvals", () => ({
  useInlineApprovals: vi.fn(() => {
    throw new Error("Owner approvals mounted")
  }),
}))

describe("shared MessageList", () => {
  it("renders saved messages with the existing native presenter without mounting owner approvals", () => {
    const messages = [
      message("user", 1, [{ part_kind: "user-prompt", content: "Find sources" }]),
      message("assistant", 2, [
        { part_kind: "text", content: "Saved answer" },
        {
          part_kind: "native-tool-call",
          tool_kind: "capability-load",
          tool_call_id: "load_cap",
          tool_name: "load_capability",
          args: '{"id":"skill-research"}',
        },
      ]),
      message("tool", 3, [
        {
          part_kind: "native-tool-return",
          tool_kind: "capability-load",
          tool_call_id: "load_cap",
          tool_name: "load_capability",
          outcome: "success",
          content: { loaded: true },
        },
        {
          part_kind: "tool-return",
          tool_name: "web_search",
          tool_call_id: "search",
          content: {
            query: "Praxis",
            model: "model",
            model_provider: "provider",
            sources: [
              {
                url: "https://example.com/source",
                title: "Published source",
                snippet: "Source content",
              },
            ],
          },
        },
      ]),
    ]
    const timeline = projectConversationTimeline({
      conversationId: "chat",
      assistantAgentId: "agent",
      messages,
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
    const client = new QueryClient()
    const html = renderToStaticMarkup(
      createElement(
        QueryClientProvider,
        { client },
        createElement(MessageList, {
          shared: true,
          timeline,
          assistantAgentMetadata: null,
          assistantLabel: "Agent",
        })
      )
    )
    expect(html).toContain("Find sources")
    expect(html).toContain("Saved answer")
    expect(html).toContain("Activated Skill: research")
    expect(html).not.toContain("Ran load_capability")
    expect(html).toContain('aria-label="Web search results for Praxis"')
    expect(html).not.toContain("Approval request")
    expect(useInlineApprovals).not.toHaveBeenCalled()
    client.clear()
  })

  it("hides awaiting approval tools before mounting any presenter or query hooks", () => {
    const html = renderToStaticMarkup(
      createElement(
        SharedTranscriptContext,
        { value: true },
        createElement(ToolCallRow, {
          activity: {
            id: "pending",
            name: "write_file",
            kind: "approval",
            status: "awaiting_approval",
            args: { content: "Pending secret" },
          },
        })
      )
    )
    expect(html).toBe("")
  })
})

function message(
  role: string,
  sequence: number,
  parts: Record<string, unknown>[]
): ConversationMessage {
  const timestamp = "2026-09-09T12:00:00Z"
  return {
    id: `message-${String(sequence)}`,
    conversation_id: "chat",
    role,
    sequence,
    parts: { parts },
    client_message_id: null,
    metadata: null,
    error: null,
    tool_name: null,
    created_at: timestamp,
    updated_at: timestamp,
  }
}
