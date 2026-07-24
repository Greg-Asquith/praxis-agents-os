// apps/web/tests/features/conversations/components/kb-tool-row.test.ts

import { createElement } from "react"
import { renderToStaticMarkup } from "react-dom/server"
import {
  RouterContextProvider,
  createMemoryHistory,
  createRootRoute,
  createRoute,
  createRouter,
} from "@tanstack/react-router"
import { describe, expect, it } from "vitest"

import { KbToolRow } from "@/features/conversations/components/kb-tool-row"
import type { ToolActivity } from "@/features/conversations/message-parts"

describe("KbToolRow", () => {
  it("shows the query while a knowledge search runs", () => {
    const html = render(
      activity({
        args: { query: "pricing tiers" },
        kind: "call",
        name: "search_knowledge",
        result: undefined,
        status: "running",
      })
    )

    expect(html).toContain('aria-busy="true"')
    expect(html).toContain("Search Knowledge")
    expect(html).toContain("Searching knowledge for pricing tiers…")
  })

  it("renders matches with document links, stripped previews, and a show-all toggle", () => {
    const html = render(
      activity({
        name: "search_knowledge",
        result: {
          query: "pricing tiers",
          results: Array.from({ length: 7 }, (_, index) => ({
            document_id: `doc-${String(index + 1)}`,
            document_title: `Pricing guide ${String(index + 1)}`,
            source_type: index === 0 ? "manual" : "url",
            is_private: index === 1,
            content:
              index === 0
                ? "## Plans\n\nSee [pricing](https://example.com/pricing) for **tier** details."
                : {
                    node: "praxis_untrusted",
                    source_kind: "kb",
                    source_ref: `chunk:chunk-${String(index + 1)}`,
                    content: "External <script>alert('no')</script> wording.",
                  },
          })),
          total: 7,
          used_lexical_fallback: false,
        },
      })
    )

    expect(html).toContain("Search Knowledge")
    expect(html).toContain("7 Matches")
    expect(html).toContain("Best match")
    expect(html).not.toContain("Rank 2")
    expect(html).toContain('href="/knowledge/doc-1"')
    expect(html).toContain("Pricing guide 1")
    expect(html).toContain("Plans See pricing for tier details.")
    expect(html).not.toContain("](https://example.com/pricing)")
    expect(html).toContain("&lt;script&gt;")
    expect(html).not.toContain("<script>")
    expect(html).toContain(">Manual<")
    expect(html).toContain("Private")
    expect(html).toContain("Show All 7 Matches")
    expect(html).toContain("Pricing guide 5")
    expect(html).not.toContain("Pricing guide 6")
  })

  it("renders an empty state instead of pretending matches exist", () => {
    const html = render(
      activity({
        name: "search_knowledge",
        result: { query: "unknown", results: [], total: 0, used_lexical_fallback: true },
      })
    )

    expect(html).toContain("No matching knowledge was found.")
    expect(html).toContain("Showing keyword matches while documents finish processing.")
    expect(html).not.toContain("Show All")
  })

  it("renders trusted document windows as markdown with a partial-read note", () => {
    const html = render(
      activity({
        name: "read_document",
        result: {
          document_id: "doc-1",
          title: "Access policy",
          source_type: "manual",
          is_private: true,
          start: 0,
          end: 28,
          total_chars: 400,
          content: "**Quarterly reviews** are required.",
        },
      })
    )

    expect(html).toContain("Read Knowledge Document")
    expect(html).toContain('href="/knowledge/doc-1"')
    expect(html).toContain("Access policy")
    expect(html).toContain("Private")
    expect(html).toContain("<strong")
    expect(html).toContain("Showing part of this document (28 of 400 characters).")
    expect(html).not.toContain("**Quarterly reviews**")
  })

  it("frames external document content instead of rendering it as markdown", () => {
    const html = render(
      activity({
        name: "read_document",
        result: {
          document_id: "doc-2",
          title: "Imported handbook",
          source_type: "url",
          is_private: false,
          start: 0,
          end: 20,
          total_chars: 20,
          content: {
            node: "praxis_untrusted",
            source_kind: "kb",
            source_ref: "document:doc-2",
            content: "[malicious](javascript:alert(1))",
          },
        },
      })
    )

    expect(html).toContain("External Content")
    expect(html).toContain("document:doc-2")
    expect(html).toContain("[malicious](javascript:alert(1))")
    expect(html).not.toContain('href="javascript:')
    expect(html).not.toContain("Showing part of this document")
  })

  it("reports failures honestly and falls through on malformed results", () => {
    const failed = render(
      activity({
        name: "search_knowledge",
        result: "The knowledge base was unavailable.",
        status: "failed",
      })
    )
    const malformed = render(activity({ name: "read_document", result: { unexpected: true } }))

    expect(failed).toContain("What Went Wrong")
    expect(failed).toContain("The knowledge base was unavailable.")
    expect(failed).toContain(">Failed<")
    expect(malformed).toBe("")
  })
})

function render(toolActivity: ToolActivity): string {
  const rootRoute = createRootRoute()
  const knowledgeDocumentRoute = createRoute({
    getParentRoute: () => rootRoute,
    path: "/knowledge/$documentId",
  })
  const router = createRouter({
    history: createMemoryHistory({ initialEntries: ["/"] }),
    routeTree: rootRoute.addChildren([knowledgeDocumentRoute]),
  })
  return renderToStaticMarkup(
    createElement(RouterContextProvider, {
      children: createElement(KbToolRow, { activity: toolActivity, defaultOpen: true }),
      router,
    })
  )
}

function activity(overrides: Partial<ToolActivity>): ToolActivity {
  return {
    id: "tool-1",
    kind: "result",
    name: "search_knowledge",
    status: "completed",
    ...overrides,
  }
}
