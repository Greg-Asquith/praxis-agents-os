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
  it("renders a live running call as a full activity card", () => {
    const html = renderRow(
      {
        id: "search-1",
        kind: "call",
        name: "web_search",
        status: "running",
        args: { query: "Praxis Agents" },
      },
      true
    )

    expect(html).toContain('aria-label="Searching the Web for Praxis Agents, in progress"')
    expect(html).toContain("Praxis Agents")
    expect(html).toContain("tool-activity-shimmer")
    expect(html).toContain("0s")
    expect(html).not.toContain("<details")
  })

  it("renders completed outcomes before arguments with a short metric", () => {
    const html = renderRow({
      id: "search-1",
      kind: "result",
      name: "web_search",
      status: "completed",
      args: { query: "Praxis Agents" },
      result: { answer: "Three sources found" },
    })

    expect(html).toContain("Searched the Web for Praxis Agents")
    expect(html).toContain("Three sources found")
    expect(html.indexOf(">Answer</p>")).toBeLessThan(html.indexOf(">Search</p>"))
    expect(html).not.toContain("0s")
  })

  it("opens live failures with plain-language framing and no technical disclosure", () => {
    const html = renderRow(
      {
        id: "search-1",
        kind: "result",
        name: "web_search",
        status: "failed",
        args: { query: "missing source" },
        result: "The requested source could not be found.",
      },
      true
    )

    expect(html).toContain("<details")
    expect(html).toContain('open=""')
    expect(html).toContain("The agent saw this error and can adjust.")
    expect(html).toContain("What went wrong")
    expect(html).not.toContain("Technical")
  })

  it("keeps the live failure explanation when no friendly result is available", () => {
    const html = renderRow(
      {
        id: "search-1",
        kind: "result",
        name: "web_search",
        status: "failed",
      },
      true
    )

    expect(html).toContain('open=""')
    expect(html).toContain("The agent saw this error and can adjust.")
    expect(html).not.toContain("What went wrong")
  })

  it("renders file outcomes as actionable entity rows inside the shared field well", () => {
    const html = renderRow({
      id: "files-1",
      kind: "result",
      name: "list_files",
      status: "completed",
      result: {
        files: [
          {
            id: "file-1",
            name: "Quarterly plan.pdf",
            category: "ingestible_document",
            media_type: "application/pdf",
            processing_status: "ready",
            size_bytes: 4096,
            updated_at: "2026-07-17T12:00:00Z",
          },
        ],
        scratch: [],
        total: 1,
      },
    })

    expect(html).toContain("Files · 1")
    expect(html).toContain('data-slot="tool-field-well"')
    expect(html).toContain('aria-label="View details for Quarterly plan.pdf"')
    expect(html).toContain('aria-label="Actions for Quarterly plan.pdf"')
    expect(html).toContain("4.0 KB")
  })

  it("renders file read details as plain-language shared fields", () => {
    const html = renderRow({
      id: "read-1",
      kind: "result",
      name: "read_file",
      status: "completed",
      result: {
        mode: "content",
        content: "# Quarterly plan",
        end_offset: 18,
        name: "plan.md",
        offset: 0,
        total_bytes: 40,
        truncated: true,
      },
    })

    expect(html).toContain("Content Read")
    expect(html).toContain("more available")
    expect(html).toContain(">Content</p>")
    expect(html).not.toContain("Byte range")
    expect(html).not.toContain("Next read")
  })

  it("places the todo checklist inside the shared field system", () => {
    const html = renderRow({
      id: "todos-1",
      kind: "result",
      name: "write_todos",
      status: "completed",
      result: {
        items: [{ content: "Review the plan", status: "in_progress" }],
        counts: { completed: 0, in_progress: 1, pending: 0 },
      },
    })

    expect(html).toContain("Plan · 1 item")
    expect(html).toContain('data-slot="tool-field-well"')
    expect(html).toContain("Review the plan")
  })

  it("renders skill document content in a shared Markdown field without JSON", () => {
    const html = renderRow({
      id: "skill-doc-1",
      kind: "result",
      name: "read_skill_document",
      status: "completed",
      args: { document: "guide", skill: "research" },
      result: "<skill-document skill='research' document='guide'>\n# Guidance\n</skill-document>",
    })

    expect(html).toContain("Document Content")
    expect(html).toContain("Guidance")
    expect(html).toContain('data-slot="tool-field-well"')
    expect(html).not.toContain("&lt;skill-document")
  })

  it("renders available delegate agents as an identity-rich mini-view", () => {
    const html = renderRow({
      id: "delegate-list-1",
      kind: "result",
      name: "list_delegate_agents",
      status: "completed",
      result: [
        {
          id: "agent-1",
          name: "Research Agent",
          description: "Finds and checks source material.",
          model: "claude-sonnet-5",
          skill_count: 2,
          slug: "research-agent",
          tool_count: 1,
        },
      ],
    })

    expect(html).toContain("Found Available Agents")
    expect(html).toContain("Agents · 1")
    expect(html).toContain("Research Agent")
    expect(html).toContain("Finds and checks source material.")
    expect(html).not.toContain("research-agent")
    expect(html).not.toContain("claude-sonnet-5")
  })
})

function renderRow(activity: ToolActivity, live = false) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  })
  queryClient.setQueryData(toolPresentationsQueryOptions().queryKey, {
    tools: [presentation],
  })

  return renderToStaticMarkup(
    createElement(QueryClientProvider, {
      client: queryClient,
      children: createElement(ToolCallRow, { activity, live }),
    })
  )
}

function field(key: string, label: string, format: "text" | "markdown" = "text") {
  return {
    key,
    label,
    format,
    editable: false,
    placeholder: "",
    options: [],
    secondary: false,
  }
}
