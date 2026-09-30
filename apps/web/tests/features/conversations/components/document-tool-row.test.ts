// apps/web/tests/features/conversations/components/document-tool-row.test.ts

import { createElement } from "react"
import { renderToStaticMarkup } from "react-dom/server"
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { describe, expect, it } from "vitest"

import { DocumentToolRow } from "@/features/conversations/components/document-tool-row"
import type { ToolActivity } from "@/features/conversations/message-parts"

const FILE_TEXT = {
  node: "praxis_untrusted",
  source_kind: "file",
  source_ref: "file:file-1/revision:revision-1",
  content: '<img src=x onerror="alert(1)">',
}

describe("DocumentToolRow", () => {
  it("opens an edit with warnings so they show, and renders file text as plain text", () => {
    const html = render(
      activity("edit_workbook", {
        file_id: "file-1",
        name: "Regional sales.xlsx",
        revision_id: "revision-2",
        revision_number: 2,
        warnings: ["Formula cells have no saved values until Excel opens the workbook."],
        changes: [{ operation: 0, summary: "Wrote 1 cells in Sales.", sheet: "Sales" }],
        readback: {
          blocks: [{ sheet: "Sales", range: "A1", cells: [{ ref: "A1", value: FILE_TEXT }] }],
        },
      })
    )

    expect(html).toContain("Formula cells have no saved values")
    expect(html).toContain("&lt;img src=x")
    expect(html).not.toContain("<img src=x")
  })

  it("renders a created File", () => {
    const html = render(
      activity("create_presentation", {
        file_id: "file-3",
        name: "Board update.pptx",
        revision_id: "revision-3",
        revision_number: 1,
        folder: { id: "folder-1", name: "Board" },
        changes: [{ operation: 0, summary: "Added slide 1.", slide_id: 256 }],
        readback: { slides: [] },
      }),
      true
    )

    expect(html).toContain('aria-label="View details for Board update.pptx"')
  })
})

function render(toolActivity: ToolActivity, defaultOpen = false): string {
  return renderToStaticMarkup(
    createElement(QueryClientProvider, {
      client: new QueryClient(),
      children: createElement(DocumentToolRow, {
        activity: toolActivity,
        defaultOpen,
        label: toolActivity.name,
        ui: null,
      }),
    })
  )
}

function activity(name: string, result: unknown): ToolActivity {
  return { id: "tool-1", kind: "result", name, status: "completed", args: {}, result }
}
