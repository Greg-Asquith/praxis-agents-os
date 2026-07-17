import { createElement, type ReactElement } from "react"
import { renderToStaticMarkup } from "react-dom/server"
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { describe, expect, it } from "vitest"

import {
  AssistantLiveActivityRow,
  AssistantTurnRow,
} from "@/features/conversations/components/message-row"
import type {
  ParsedConversationMessage,
  ToolActivity,
} from "@/features/conversations/message-parts"

const activity: ToolActivity = {
  id: "search-1",
  kind: "call",
  name: "web_search",
  status: "running",
  args: { query: "Praxis Agents" },
}

describe("assistant turn content order", () => {
  it("renders persisted thinking before tool activity", () => {
    const message: ParsedConversationMessage = {
      id: "message-1",
      role: "assistant",
      sequence: 1,
      agentRunId: "run-1",
      clientMessageId: null,
      createdAt: "2026-07-17T12:00:00Z",
      text: ["Visible answer"],
      thinking: ["Hidden reasoning"],
      attachments: [],
      toolActivities: [activity],
      unsupportedParts: [],
    }

    const html = renderWithQuery(
      createElement(AssistantTurnRow, {
        assistantAgentId: "agent-1",
        createdAt: message.createdAt,
        messages: [message],
        toolActivities: [activity],
      })
    )

    expect(html.indexOf("Thinking")).toBeLessThan(html.indexOf("web_search"))
  })

  it("renders live thinking before tool activity", () => {
    const html = renderWithQuery(
      createElement(AssistantLiveActivityRow, {
        assistantAgentId: "agent-1",
        isStreaming: true,
        messages: [
          {
            channel: "thinking",
            id: "thinking-1",
            role: "assistant",
            status: "streaming",
            text: "Hidden reasoning",
          },
        ],
        toolActivities: [activity],
      })
    )

    expect(html.indexOf("Thinking")).toBeLessThan(html.indexOf("web_search"))
  })
})

function renderWithQuery(element: ReactElement) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  })
  return renderToStaticMarkup(
    createElement(QueryClientProvider, { client: queryClient, children: element })
  )
}
