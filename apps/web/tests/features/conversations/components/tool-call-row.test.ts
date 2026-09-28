// apps/web/tests/features/conversations/components/tool-call-row.test.ts

import { createElement } from "react"
import { renderToStaticMarkup } from "react-dom/server"
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { describe, expect, it } from "vitest"

import { ToolCallRow } from "@/features/conversations/components/tool-call-row"
import type { ToolActivity } from "@/features/conversations/message-parts"
import { toolPresentationsQueryOptions } from "@/features/tools/api/list-tool-presentations"
import type { ToolPresentationEntry } from "@/features/tools/types"

const presentation: ToolPresentationEntry = {
  name: "web_search",
  provider: "native",
  label: "Web Search",
  effect: "read",
  ui: {
    icon: "globe",
    running_label: "Searching the Web for {query}",
    completed_label: "Searched the Web for {query}",
    failed_label: "Couldn't Search the Web",
    approval_title: "Search the Web",
    approval_prompt: "The agent wants to search the web for {query}.",
    approve_label: "Approve & Search",
    arg_fields: [field("query", "Search")],
    result_fields: [field("answer", "Answer", "markdown")],
  },
}

describe("ToolCallRow lifecycle", () => {
  it("renders structured untrusted nodes as plain content in the default row", () => {
    const html = renderRow(
      {
        id: "node-1",
        kind: "result",
        name: "node_tool",
        status: "completed",
        result: {
          content: {
            node: "praxis_untrusted",
            source_kind: "gmail_message",
            source_ref: "message-1",
            content: "Visible email content",
          },
        },
      },
      false,
      [
        {
          ...presentation,
          name: "node_tool",
          label: "Node Tool",
          provider: "native",
          ui: { ...presentation.ui, result_fields: [field("content", "Content", "multiline")] },
        },
      ]
    )

    expect(html).toContain("Visible email content")
    expect(html).not.toContain("praxis_untrusted")
    expect(html).not.toContain("PRAXIS_UNTRUSTED_CONTENT")
  })

  it("shows retained failure excerpts in compact nested calls without exposing raw results", () => {
    const html = renderRow(
      {
        id: "nested-failure",
        kind: "result",
        name: "unregistered_tool",
        parentToolCallId: "workflow-1",
        status: "failed",
        result: { internal_payload: "Do not show raw JSON" },
        resultExcerpt: "The requested file was not found.",
      },
      false,
      [presentation],
      true,
      true
    )

    expect(html).toContain("<section")
    expect(html).toContain("The requested file was not found.")
    expect(html).not.toContain("internal_payload")
    expect(html).not.toContain("<details")
  })

  it("renders error text as text rather than executable markup", () => {
    const html = renderRow(
      {
        id: "script-failure",
        kind: "result",
        name: "run_code",
        status: "failed",
        result: '<script>alert("error")</script>',
      },
      false,
      [presentation],
      true
    )

    expect(html).toContain("&lt;script&gt;")
    expect(html).not.toContain("<script>")
  })
})

function renderRow(
  activity: ToolActivity,
  live = false,
  presentations: ToolPresentationEntry[] = [presentation],
  defaultOpen = false,
  compact = false
) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  })
  queryClient.setQueryData(toolPresentationsQueryOptions().queryKey, {
    tools: presentations,
  })

  return renderToStaticMarkup(
    createElement(QueryClientProvider, {
      client: queryClient,
      children: createElement(ToolCallRow, { activity, compact, defaultOpen, live }),
    })
  )
}

function field(key: string, label: string, format: "text" | "markdown" | "multiline" = "text") {
  return {
    key,
    label,
    min_rows: 0,
    format,
    editable: false,
    placeholder: "",
    options: [],
    secondary: false,
  }
}
