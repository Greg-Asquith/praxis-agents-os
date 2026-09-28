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
