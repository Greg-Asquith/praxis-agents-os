import { createElement } from "react"
import { renderToStaticMarkup } from "react-dom/server"
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { describe, expect, it } from "vitest"

import { FilesTable } from "@/features/files/components/files-table"
import {
  fileSelectionReducer,
  initialFileSelectionState,
} from "@/features/files/components/file-selection"
import type { WorkspaceFile } from "@/features/files/types"

const file: WorkspaceFile = {
  category: "editable_text",
  content_hash: "hash",
  content_type: "text/markdown",
  created_at: "2026-08-12T09:00:00Z",
  current_revision_id: "revision-1",
  description: "Release notes",
  extension: "md",
  folder_id: null,
  folder_name: null,
  id: "file-1",
  name: "Launch notes.md",
  processing_error: null,
  processing_status: "ready",
  revision_count: 1,
  size_bytes: 2048,
  updated_at: "2026-08-12T10:00:00Z",
  workspace_id: "workspace-1",
}

describe("FilesTable", () => {
  it("clears selection after a scope change and a successful move", () => {
    const selected = fileSelectionReducer(initialFileSelectionState("root:1"), {
      fileId: file.id,
      selected: true,
      type: "selection-change",
    })
    const moving = fileSelectionReducer(selected, {
      fileIds: [file.id],
      type: "move-open",
    })

    const moved = fileSelectionReducer(moving, { type: "move-success" })
    expect([...moved.selectedIds]).toEqual([])
    expect(moved.moveFileIds).toEqual([])

    const nextScope = fileSelectionReducer(moving, {
      scope: "folder-1:1",
      type: "scope-change",
    })
    expect([...nextScope.selectedIds]).toEqual([])
    expect(nextScope.moveFileIds).toEqual([])
  })

  it("renders the active server sort through the app-table header", () => {
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    })
    const html = renderToStaticMarkup(
      createElement(QueryClientProvider, {
        client: queryClient,
        children: createElement(FilesTable, {
          files: [file],
          isChangingView: false,
          limit: 25,
          offset: 0,
          onOpenFile: () => undefined,
          onPageChange: () => undefined,
          onSortChange: () => undefined,
          selectionScope: "root:1",
          sortBy: "name",
          sortDirection: "asc",
          total: 1,
        }),
      })
    )

    expect(html).toContain('aria-sort="ascending"')
    expect(html.match(/aria-sort="none"/g)).toHaveLength(5)
    expect(html).toContain("Sort: Name")
    expect(html).toContain("Launch notes.md")
    expect(html).toContain('aria-label="Select Launch notes.md"')
    expect(html).toContain("table-fixed")
    expect(html).toContain('data-slot="tooltip-trigger"')
    expect(html).toContain("max-w-full truncate text-left font-medium")
    expect(html).toContain("Showing 1-1 of 1")
  })
})
