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

    expectOrdered(html, ["Thinking", "Introduction", "Praxis Agents", "Conclusion"])
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

    expectOrdered(html, ["Thinking", "Introduction", "Praxis Agents", "Conclusion"])
    expect(html).toContain('aria-busy="true"')
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

    expectOrdered(html, ["Legacy answer", "Praxis Agents"])
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

    expect(html).toContain("Praxis Agents")
    expect(html).toContain("Searching Praxis Agents…")
  })

  it("turns an internal workspace-file Markdown link into a download action", () => {
    const fileId = "245de7d6-0963-4ba4-9b63-45fe64526252"
    const message: ParsedConversationMessage = {
      id: "file-link-message",
      role: "assistant",
      sequence: 1,
      agentRunId: "run-1",
      clientMessageId: null,
      createdAt: "2026-08-14T12:00:00Z",
      parts: [
        {
          kind: "text",
          id: "file-link-message:0",
          content: `[Download the PowerPoint deck](/files?fileId=${fileId})`,
        },
      ],
      text: [`[Download the PowerPoint deck](/files?fileId=${fileId})`],
      thinking: [],
      attachments: [],
      toolActivities: [],
      unsupportedParts: [],
    }

    const html = renderWithQuery(
      createElement(AssistantTurnRow, {
        assistantAgentId: "agent-1",
        createdAt: message.createdAt,
        messages: [message],
      })
    )

    expect(html).toContain(`data-workspace-file-download="${fileId}"`)
    expect(html).toContain(`href="/files?fileId=${fileId}"`)
    expect(html).toContain("Download the PowerPoint deck")
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

  it("renders only the newest valid plan update in the live timeline", () => {
    const firstPlan = todoActivity("live-plan-1", "Inspect the old plan", "pending")
    const currentPlan = todoActivity("live-plan-2", "Implement the current plan", "in_progress")
    const html = renderWithQuery(
      createElement(AssistantLiveActivityRow, {
        assistantAgentId: "agent-1",
        isStreaming: true,
        messages: [],
        timeline: [
          { kind: "tool", activity: firstPlan },
          { kind: "tool", activity: currentPlan },
        ],
      })
    )

    expect(html).not.toContain("Inspect the old plan")
    expect(html).toContain("Implement the current plan")
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
