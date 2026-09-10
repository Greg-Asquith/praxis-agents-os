import { createElement } from "react"
import { renderToStaticMarkup } from "react-dom/server"
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { describe, expect, it } from "vitest"

import { FilesTable } from "@/features/files/components/files-table"
import {
  fileSelectionReducer,
  initialFileSelectionState,
} from "@/features/files/components/file-selection"
import type { FileListEntry } from "@/features/files/list-entries"
import type { FileFolder, WorkspaceFile } from "@/features/files/types"

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
  scope: "workspace",
  is_published: false,
  can_manage_platform: false,
  published_revision_id: null,
}

const folder: FileFolder = {
  created_at: "2026-08-18T09:00:00Z",
  description: "Launch collateral",
  file_count: 3,
  id: "folder-1",
  name: "Launch pack",
  total_bytes: 4096,
  updated_at: "2026-08-18T10:00:00Z",
  workspace_id: "workspace-1",
}

const baseProps = {
  canEdit: true,
  isChangingView: false,
  limit: 25,
  offset: 0,
  onOpenFile: () => undefined,
  onPageChange: () => undefined,
  onSortChange: () => undefined,
  sortBy: "name",
  sortDirection: "asc",
} as const

type TableProps = Parameters<typeof FilesTable>[0]

function entriesOf(files: WorkspaceFile[], folders: FileFolder[] = []): FileListEntry[] {
  return [
    ...folders.map((folder): FileListEntry => ({ folder, kind: "folder" })),
    ...files.map((file): FileListEntry => ({ file, kind: "file" })),
  ]
}

function renderTable({
  files = [file],
  folders = [],
  ...props
}: Partial<Omit<TableProps, "entries">> & { files?: WorkspaceFile[] }) {
  return renderToStaticMarkup(
    createElement(QueryClientProvider, {
      client: new QueryClient({ defaultOptions: { queries: { retry: false } } }),
      children: createElement(FilesTable, {
        ...baseProps,
        entries: entriesOf(files, folders),
        folders,
        selectionScope: "root:1",
        total: 1,
        ...props,
      }),
    })
  )
}

describe("FilesTable", () => {
  it("clears selection after a scope change, a bulk set, and a successful move", () => {
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

    const all = fileSelectionReducer(selected, { fileIds: ["a", "b"], type: "selection-set" })
    expect([...all.selectedIds]).toEqual(["a", "b"])
    expect([
      ...fileSelectionReducer(all, { fileIds: [], type: "selection-set" }).selectedIds,
    ]).toEqual([])
  })

  it.each([true, false])(
    "shows shared files with published state %s and appropriate actions",
    (published) => {
      const html = renderTable({
        files: [{ ...file, scope: "platform", workspace_id: null, is_published: published }],
        selectionScope: "platform:1",
      })
      expect(html.match(/>Shared</g)).toHaveLength(2)
      expect(html).not.toContain("Select all files on this page")
      expect(html).not.toContain('aria-label="Select Launch notes.md"')
      expect(html).toContain('pr-0 w-10"')
      expect(html).not.toContain(">Move<")
      expect(html).not.toContain(">Delete<")
      if (published) expect(html).toContain(">Download<")
      else {
        expect(html).not.toContain(">Download<")
        expect(html).not.toContain(">Open<")
        expect(html).toContain(">Details<")
      }
    }
  )

  it("keeps read-only file and folder access without editing controls", () => {
    const html = renderTable({ canEdit: false, folders: [folder] })

    expect(html).toContain('aria-label="Open folder Launch pack"')
    expect(html).toContain('aria-label="Open Details for Launch notes.md"')
    expect(html).toContain(">Download<")
    expect(html).not.toContain("Select all files on this page")
    expect(html).not.toContain('aria-label="Select Launch notes.md"')
    expect(html).not.toContain("Actions for Launch pack")
    expect(html).not.toContain(">Move<")
    expect(html).not.toContain(">Delete<")
  })

  it("renders the active server sort, selection, and file details in one row", () => {
    const html = renderTable({})

    expect(html).toContain('aria-sort="ascending"')
    expect(html.match(/aria-sort="none"/g)).toHaveLength(2)
    expect(html).not.toContain(">Type<")
    expect(html).not.toContain(">Status<")
    expect(html).not.toContain(">Created<")
    expect(html).toContain("Sort: Name")
    expect(html).toContain("Launch notes.md")
    expect(html).toContain("Markdown · Release notes")
    expect(html).not.toContain(">Ready<")
    expect(html).toContain('aria-label="Select all files on this page"')
    expect(html).toContain('aria-label="Select Launch notes.md"')
    expect(html).toContain("table-fixed")
    expect(html).toContain('data-slot="tooltip-trigger"')
    expect(html).toContain("min-w-0 truncate text-left font-medium")
    expect(html).toContain("Showing 1-1 of 1")
  })

  it("shows processing state inline and the folder a search result lives in", () => {
    const html = renderTable({
      files: [
        {
          ...file,
          folder_id: folder.id,
          folder_name: folder.name,
          processing_status: "processing",
        },
      ],
    })

    expect(html).toContain(">Processing<")
    expect(html).toContain("In Launch pack")

    const insideFolder = renderTable({
      files: [{ ...file, folder_id: folder.id, folder_name: folder.name }],
      inFolder: true,
    })
    expect(insideFolder).not.toContain("In Launch pack")
  })

  it("renders folders and files as rows of one table without group labels", () => {
    const html = renderTable({ folders: [folder] })

    expect(html.indexOf("Launch pack")).toBeLessThan(html.indexOf("Launch notes.md"))
    expect(html).not.toContain("Folders <span")
    expect(html).not.toContain("Files <span")
    expect(html).not.toContain('aria-label="Next folders"')
    expect(html).toContain('aria-label="Open folder Launch pack"')
    expect(html).toContain("3 files · Launch collateral")
    expect(html).toContain("Actions for Launch pack")
    expect(html).not.toMatch(/colspan/i)
  })

  it("paginates folders and files together as one list", () => {
    const html = renderTable({ files: [], folders: [folder], limit: 10, total: 1 })

    expect(html).toContain("Launch pack")
    expect(html).toContain("Showing")
    expect(html).not.toContain("Add your first files")
  })

  it("shows the first-run empty state with a dashed drop target", () => {
    const html = renderTable({
      emptyClassName: "border-dashed",
      files: [],
      total: 0,
    })

    expect(html).toContain("Add your first files")
    expect(html).toContain("border-dashed")
  })
})
