import { createElement, type ReactElement } from "react"
import { renderToStaticMarkup } from "react-dom/server"
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { describe, expect, it } from "vitest"

import { AssistantTurnRow } from "@/features/conversations/components/message-row"
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

    expectOrdered(html, ["Thinking", "Introduction", "Praxis Agents", "Conclusion"])
  })

  it("renders only the newest valid plan update in a persisted assistant turn", () => {
    const firstPlan = todoActivity("plan-1", "Draft the first version", "pending")
    const currentPlan = todoActivity("plan-2", "Review the current version", "in_progress")
    const message: ParsedConversationMessage = {
      id: "plan-message",
      role: "assistant",
      sequence: 1,
      agentRunId: "run-1",
      clientMessageId: null,
      createdAt: "2026-07-17T12:00:00Z",
      parts: [
        { kind: "tool", id: "plan-message:0", activity: firstPlan },
        { kind: "tool", id: "plan-message:1", activity: currentPlan },
      ],
      text: [],
      thinking: [],
      attachments: [],
      toolActivities: [firstPlan, currentPlan],
      unsupportedParts: [],
    }

    const html = renderWithQuery(
      createElement(AssistantTurnRow, {
        assistantAgentId: "agent-1",
        createdAt: message.createdAt,
        messages: [message],
      })
    )

    expect(html).not.toContain("Draft the first version")
    expect(html).toContain("Review the current version")
    expect(html.match(/data-slot="plan-card"/g) ?? []).toHaveLength(1)
  })
})

function todoActivity(
  id: string,
  content: string,
  status: "pending" | "in_progress" | "completed"
): ToolActivity {
  return {
    id,
    kind: "result",
    name: "write_todos",
    status: "completed",
    result: { items: [{ content, status }] },
  }
}

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
