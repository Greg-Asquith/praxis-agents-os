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
  it("renders persisted thinking first and visible parts in source order", () => {
    const message: ParsedConversationMessage = {
      id: "message-1",
      role: "assistant",
      sequence: 1,
      agentRunId: "run-1",
      clientMessageId: null,
      createdAt: "2026-07-17T12:00:00Z",
      parts: [
        { kind: "thinking", id: "message-1:0", content: "Hidden reasoning" },
        { kind: "text", id: "message-1:1", content: "Introduction" },
        { kind: "tool", id: "message-1:2", activity },
        { kind: "text", id: "message-1:3", content: "Conclusion" },
      ],
      text: ["Introduction", "Conclusion"],
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
      })
    )

    expectOrdered(html, ["Thinking", "Introduction", "web_search", "Conclusion"])
  })

  it("renders live thinking first and timeline parts in arrival order", () => {
    const introduction = {
      channel: "text" as const,
      id: "text-1",
      role: "assistant" as const,
      status: "complete" as const,
      text: "Introduction",
      timelineSequence: 0,
    }
    const conclusion = {
      channel: "text" as const,
      id: "text-2",
      role: "assistant" as const,
      status: "streaming" as const,
      text: "Conclusion",
      timelineSequence: 2,
    }
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
            timelineSequence: 3,
          },
          introduction,
          conclusion,
        ],
        timeline: [
          { kind: "text", message: introduction },
          { kind: "tool", activity },
          { kind: "text", message: conclusion },
        ],
      })
    )

    expectOrdered(html, ["Thinking", "Introduction", "web_search", "Conclusion"])
    expect(html).toContain("in progress")
    expect(html).toContain("0s")
    expect(html.indexOf("<details")).toBeLessThan(html.indexOf("<section"))
  })

  it("uses grouped text-then-tool order when persisted source order is unavailable", () => {
    const message: ParsedConversationMessage = {
      id: "legacy-message",
      role: "assistant",
      sequence: 1,
      agentRunId: "run-1",
      clientMessageId: null,
      createdAt: "2026-07-17T12:00:00Z",
      parts: null,
      text: ["Legacy answer"],
      thinking: [],
      attachments: [],
      toolActivities: [activity],
      unsupportedParts: [],
    }

    const html = renderWithQuery(
      createElement(AssistantTurnRow, {
        assistantAgentId: "agent-1",
        createdAt: message.createdAt,
        messages: [message],
      })
    )

    expectOrdered(html, ["Legacy answer", "web_search"])
  })

  it("renders a persisted tool-only assistant message", () => {
    const message: ParsedConversationMessage = {
      id: "tool-only-message",
      role: "assistant",
      sequence: 1,
      agentRunId: "run-1",
      clientMessageId: null,
      createdAt: "2026-07-17T12:00:00Z",
      parts: [{ kind: "tool", id: "tool-only-message:0", activity }],
      text: [],
      thinking: [],
      attachments: [],
      toolActivities: [activity],
      unsupportedParts: [],
    }

    const html = renderWithQuery(
      createElement(AssistantTurnRow, {
        assistantAgentId: "agent-1",
        createdAt: message.createdAt,
        messages: [message],
      })
    )

    expect(html).toContain("web_search")
    expect(html).toContain("Running web_search")
  })
})

function expectOrdered(value: string, fragments: string[]) {
  let previousIndex = -1
  for (const fragment of fragments) {
    const index = value.indexOf(fragment)
    expect(index).toBeGreaterThan(previousIndex)
    previousIndex = index
  }
}

function renderWithQuery(element: ReactElement) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  })
  return renderToStaticMarkup(
    createElement(QueryClientProvider, { client: queryClient, children: element })
  )
}
