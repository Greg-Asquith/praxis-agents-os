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
  it.each(["web_search", "write_file", "run_workflow", "delegate_to_agent", "unknown_tool"])(
    "shows the stopped card instead of a success presenter for %s",
    (name) => {
      const activity: ToolActivity = {
        id: "stopped-1",
        name,
        kind: "call",
        status: "stopped",
        result: "The run reached its limit.",
      }
      const collapsed = renderRow(activity)
      expect(collapsed).toContain(">Stopped</span>")
      expect(collapsed).toContain('aria-expanded="false"')
      const expanded = renderRow(activity, false, [presentation], true)
      expect(expanded).toContain("Why this call stopped")
      expect(expanded).toContain("The run reached its limit.")
      expect(expanded).not.toContain(">Done</span>")
      expect(expanded).not.toContain(">Failed</span>")
      const missingReason = renderRow({ ...activity, result: null }, true, [presentation], true)
      expect(missingReason).toContain("Its outcome is unconfirmed.")
    }
  )

  it("renders a live web search with its query and search skeleton", () => {
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

    expect(html).toContain('aria-label="Searching Praxis Agents…"')
    expect(html).toContain("Praxis Agents")
    expect(html).toContain('aria-busy="true"')
    expect(html).toContain('data-slot="skeleton"')
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

  it.each([false, true])("starts failed result cards collapsed (live: %s)", (live) => {
    const html = renderRow(
      {
        id: "search-1",
        kind: "result",
        name: "web_search",
        status: "failed",
        args: { query: "missing source" },
        result: "The requested source could not be found.",
      },
      live
    )

    expect(html).toContain('data-slot="tool-result-card"')
    expect(html).toContain('<section aria-label="Web Search failed"')
    expect(html).toContain('aria-label="Expand results"')
    expect(html).toContain('aria-expanded="false"')
    expect(html).toContain(">Details</button>")
    expect(html).toContain("Search: missing source")
    expect(html).not.toContain("What went wrong")
    expect(html).not.toContain("The requested source could not be found.")
    expect(html).not.toContain("Request details")
    expect(html).not.toContain("Any further attempts")
    expect(html).not.toContain("<details")
    expect(html).not.toContain("can adjust its next attempt")
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
      true,
      [presentation],
      true
    )

    expect(html).toContain("No further error details were recorded.")
    expect(html).toContain("What went wrong")
    expect(html).not.toContain("<details")
  })

  it.each(["run_code", "fetch_url", "unregistered_tool"])(
    "uses the shared error card for %s when its presenter has no failure view",
    (name) => {
      const html = renderRow(
        {
          id: "failed-1",
          kind: "result",
          name,
          status: "failed",
          result: "The service is temporarily unavailable.",
        },
        false,
        [presentation],
        true
      )

      expect(html).toContain("<section")
      expect(html).toContain("What went wrong")
      expect(html).toContain("The service is temporarily unavailable.")
      expect(html).not.toContain("<details")
    }
  )

  it("preserves a tool's dedicated failure card", () => {
    const html = renderRow({
      id: "image-failure",
      kind: "result",
      name: "generate_image",
      status: "failed",
      result: "The service is temporarily unavailable.",
    })

    expect(html).toContain('aria-label="Generate Image failed"')
    expect(html).toContain("The service is temporarily unavailable.")
    expect(html).not.toContain("Any further attempts")
  })

  it.each([{ kind: "retry" as const }, { kind: "result" as const, outcome: "retry" }])(
    "explains a recorded retry without claiming another attempt has started: %s",
    (retry) => {
      const html = renderRow(
        {
          ...retry,
          id: "script-retry",
          name: "run_code",
          status: "failed",
          result: "Choose a supported file format.",
        },
        false,
        [presentation],
        true
      )

      expect(html).toContain("The agent received this error and can adjust its next attempt.")
      expect(html).not.toContain("Retrying")
      expect(html).toContain('aria-label="Collapse results"')
      expect(html).not.toContain(">Try again<")
    }
  )

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

  it("opens live denials and shows the operator reason separately", () => {
    const html = renderRow(
      {
        id: "search-1",
        kind: "result",
        name: "web_search",
        status: "denied",
        args: { query: "sensitive topic" },
        result:
          "The user declined this action, so it was not performed. Reason: Use the approved source.",
        decisionReason: "Use the approved source.",
      },
      true
    )

    expect(html).toContain('open=""')
    expect(html).toContain("This action was declined and was not performed.")
    expect(html).toContain("Message to Agent")
    expect(html).toContain("Use the approved source.")
    expect(html).not.toContain("What went wrong")
  })

  it("renders file outcomes as actionable entity rows inside the shared field well", () => {
    const html = renderRow(
      {
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
          total: 1,
        },
      },
      false,
      [presentation],
      true
    )

    expect(html).toContain("1 File")
    expect(html).toContain(">Details<")
    expect(html).not.toContain('data-slot="tool-field-well"')
    expect(html).toContain('aria-label="View details for Quarterly plan.pdf"')
    expect(html).toContain('aria-label="Actions for Quarterly plan.pdf"')
    expect(html).toContain("4.0 KB")
  })

  it("renders file read details as plain-language shared fields", () => {
    const html = renderRow(
      {
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
      },
      false,
      [presentation],
      true
    )

    expect(html).toContain("Content Read")
    expect(html).toContain("More content is available.")
    expect(html).toContain(">Content</p>")
    expect(html).not.toContain("Byte range")
    expect(html).not.toContain("Next read")
  })

  it("renders artifact results through the dedicated presenter", () => {
    const html = renderRow(
      {
        id: "artifact-1",
        kind: "result",
        name: "update_artifact",
        status: "completed",
        result: {
          artifact_id: "artifact-1",
          version_id: "version-2",
          title: "Launch map",
          artifact_type: "mermaid",
        },
      },
      false,
      [presentation],
      true
    )

    expect(html).toContain("Update Artifact")
    expect(html).toContain("Launch map")
    expect(html).toContain("Mermaid artifact")
    expect(html).toContain('aria-label="Open artifact Launch map"')
    expect(html).not.toContain("Ran update_artifact")
    expect(html).not.toContain('data-slot="tool-field-well"')
  })

  it("renders the todo checklist as a dedicated plan card", () => {
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

    expect(html).toContain('data-slot="plan-card"')
    expect(html).toContain("0 of 1 done")
    expect(html).toContain("In progress")
    expect(html).toContain("Review the plan")
    expect(html).not.toContain('data-slot="tool-field-well"')
  })

  it("falls back to the default tool row for a malformed todo payload", () => {
    const html = renderRow({
      id: "todos-bad",
      kind: "result",
      name: "write_todos",
      status: "completed",
      args: { items: [{ content: "Original", status: "pending" }] },
      result: { items: [{ content: "", status: "unknown" }] },
    })

    expect(html).toContain("Ran write_todos")
    expect(html).not.toContain('data-slot="plan-card"')
  })

  it("renders skill document content in a kit result card without JSON", () => {
    const html = renderRow(
      {
        id: "skill-doc-1",
        kind: "result",
        name: "read_skill_document",
        status: "completed",
        args: { document: "guide", skill: "research" },
        result: "<skill-document skill='research' document='guide'>\n# Guidance\n</skill-document>",
      },
      false,
      [presentation],
      true
    )

    expect(html).toContain("Read Skill Document")
    expect(html).toContain("Guidance")
    expect(html).toContain(">Details<")
    expect(html).not.toContain('data-slot="tool-field-well"')
    expect(html).not.toContain("&lt;skill-document")
  })

  it("renders available delegate agents as an identity-rich mini-view", () => {
    const html = renderRow(
      {
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
      },
      false,
      [presentation],
      true
    )

    expect(html).toContain("Available Agents")
    expect(html).toContain("1 Agent")
    expect(html).toContain("Research Agent")
    expect(html).toContain("Finds and checks source material.")
    expect(html).not.toContain("research-agent")
    expect(html).not.toContain("claude-sonnet-5")
    expect(html).not.toContain('data-slot="tool-field-well"')
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
