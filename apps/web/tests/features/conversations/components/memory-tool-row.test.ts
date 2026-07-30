// apps/web/tests/features/conversations/components/memory-tool-row.test.ts

import { createElement } from "react"
import { renderToStaticMarkup } from "react-dom/server"
import { describe, expect, it } from "vitest"

import type { ToolApprovalDecisionControls } from "@/components/tool-ui/approval-card"
import { MemoryToolRow } from "@/features/conversations/components/memory-tool-row"
import type { ToolActivity } from "@/features/conversations/message-parts"

describe("MemoryToolRow", () => {
  it("shows the memory title while a save runs", () => {
    const html = render(
      activity({
        args: { title: "Prefers concise replies" },
        kind: "call",
        name: "save_memory",
        result: undefined,
        status: "running",
      })
    )

    expect(html).toContain('aria-busy="true"')
    expect(html).toContain("Save Memory")
    expect(html).toContain("Saving memory Prefers concise replies…")
  })

  it("keeps the core-memory warning visible while approval is pending", () => {
    const html = renderToStaticMarkup(
      createElement(MemoryToolRow, {
        activity: activity({
          args: {
            title: "Release guardrail",
            content: "Require launch evidence.",
            kind: "core",
            scope: "workspace",
          },
          kind: "approval",
          name: "save_memory",
          result: undefined,
          status: "awaiting_approval",
        }),
        approvalDecision: approvalControls(),
        defaultOpen: true,
      })
    )

    expect(html).toContain("Requires Approval")
    expect(html).toContain(">Core<")
    expect(html).toContain("Workspace scope")
    expect(html).toContain("trusted memory")
  })

  it("renders a saved memory with scope and kind badges", () => {
    const html = render(
      activity({
        name: "save_memory",
        result: { status: "created", memory: memorySummary(), similarity: null },
      })
    )

    expect(html).toContain("Save Memory")
    expect(html).toContain(">Saved<")
    expect(html).toContain("Prefers concise replies")
    expect(html).toContain(">Personal<")
    expect(html).toContain(">Note<")
    expect(html).toContain("Preference")
  })

  it("explains near duplicates instead of pretending a save happened", () => {
    const html = render(
      activity({
        name: "save_memory",
        result: {
          status: "near_duplicate",
          existing_memory: memorySummary(),
          similarity: 0.95,
          next_step: "For a true duplicate, call save_memory again with duplicate_of set.",
        },
      })
    )

    expect(html).toContain(">Not Saved<")
    expect(html).toContain("A very similar memory already exists")
    expect(html).toContain("95%")
    expect(html).toContain("so nothing new was saved.")
    expect(html).toContain("Prefers concise replies")
  })

  it("renders search matches with line-broken previews and a show-all toggle", () => {
    const html = render(
      activity({
        name: "search_memory",
        result: {
          query: "reply style",
          results: Array.from({ length: 7 }, (_, index) => ({
            ...searchHit(),
            id: `m-${String(index + 1)}`,
            title: `Memory ${String(index + 1)}`,
          })),
          total: 7,
          matches_found: 9,
          results_truncated: true,
          used_lexical_fallback: true,
          next_step: "Search again with narrower terms.",
        },
      })
    )

    expect(html).toContain("Search Memory")
    expect(html).toContain("7 Matches")
    expect(html).toContain("Best match")
    expect(html).toContain("Memory 1")
    expect(html).toContain("Memory 5")
    expect(html).not.toContain("Memory 6")
    expect(html).toContain("Show All 7 Matches")
    expect(html).toContain("Showing the top 7 of 9 matches.")
    expect(html).toContain("Some match content was shortened to fit.")
    expect(html).toContain("Style\nKeep replies short.")
    expect(html).not.toContain("**short**")
  })

  it("renders an empty state when no memories match", () => {
    const html = render(
      activity({
        name: "search_memory",
        result: {
          query: "unknown",
          results: [],
          total: 0,
          matches_found: 0,
          results_truncated: false,
          used_lexical_fallback: false,
        },
      })
    )

    expect(html).toContain("No matching memories were found.")
    expect(html).not.toContain("Show All")
  })

  it("notes kept history when an update supersedes the old content", () => {
    const html = render(
      activity({
        name: "update_memory",
        result: {
          status: "superseded",
          memory: memorySummary(),
          superseded_memory_id: "m-0",
        },
      })
    )

    expect(html).toContain("Update Memory")
    expect(html).toContain(">Updated<")
    expect(html).toContain("The content changed, so the previous version was kept in history.")
  })

  it("reports archived memories without pretending a repeat archive did anything", () => {
    const archived = render(
      activity({
        name: "forget_memory",
        result: { status: "archived", memory: memorySummary() },
      })
    )
    const repeat = render(
      activity({
        name: "forget_memory",
        result: { status: "already_archived", memory: memorySummary() },
      })
    )

    expect(archived).toContain("Forget Memory")
    expect(archived).toContain(">Archived<")
    expect(archived).toContain("This memory was archived and will no longer be used.")
    expect(repeat).toContain("This memory was already archived.")
  })

  it("reports failures honestly and falls through on malformed results", () => {
    const failed = render(
      activity({
        name: "save_memory",
        result: "The memory store was unavailable.",
        status: "failed",
      })
    )
    const denied = render(
      activity({
        name: "update_memory",
        result: undefined,
        status: "denied",
      })
    )
    const malformed = render(activity({ name: "forget_memory", result: { unexpected: true } }))

    expect(failed).toContain("What Went Wrong")
    expect(failed).toContain("The memory store was unavailable.")
    expect(failed).toContain(">Failed<")
    expect(denied).toContain("Action Declined")
    expect(denied).toContain("This memory action was declined. Nothing was changed.")
    expect(malformed).toBe("")
  })
})

function render(toolActivity: ToolActivity): string {
  return renderToStaticMarkup(
    createElement(MemoryToolRow, { activity: toolActivity, defaultOpen: true })
  )
}

function activity(overrides: Partial<ToolActivity>): ToolActivity {
  return {
    id: "tool-1",
    kind: "result",
    name: "save_memory",
    status: "completed",
    ...overrides,
  }
}

function approvalControls(): ToolApprovalDecisionControls {
  return {
    decision: { decision: "pending", edits: {}, message: "" },
    error: null,
    onDecisionChange: () => undefined,
    onRetry: () => undefined,
    pendingCount: 1,
    submitting: false,
  }
}

function memorySummary() {
  return {
    id: "m-1",
    scope: "user",
    kind: "note",
    memory_type: "preference",
    title: "Prefers concise replies",
    importance: 3,
    confidence: 0.8,
    status: "active",
  }
}

function searchHit() {
  return {
    id: "m-1",
    scope: "workspace",
    kind: "core",
    memory_type: "fact",
    title: "Memory",
    content: "## Style\n\nKeep replies **short**.",
    content_truncated: false,
    source: "interactive",
    created_by: "agent",
    created_by_user_id: null,
    effective_confidence: 0.8,
    score: 0.72,
  }
}
