import { createElement, type PropsWithChildren } from "react"
import { renderToStaticMarkup } from "react-dom/server"
import { beforeEach, expect, it, vi } from "vitest"

import { FilesRoute } from "@/features/files/routes/files-route"
import type { WorkspaceRole } from "@/features/workspaces/types"

const state = vi.hoisted(() => {
  const membership: { role: WorkspaceRole | null } = { role: "member" }
  return {
    ...membership,
    files: [] as unknown[],
    folder: undefined as string | undefined,
    folders: [] as { id: string; name: string; description: string | null; updated_at?: string }[],
    page: undefined as number | undefined,
    q: undefined as string | undefined,
    scope: "platform",
    superAdmin: true,
    queries: [] as unknown[],
    tableProps: null as Record<string, unknown> | null,
  }
})
vi.mock("@tanstack/react-router", () => ({
  Link: ({ children }: PropsWithChildren) => createElement("a", null, children),
  Navigate: () => null,
  useNavigate: () => vi.fn(),
  useSearch: () => ({
    folder: state.folder,
    page: state.page,
    q: state.q,
    scope: state.scope,
  }),
}))
vi.mock("@tanstack/react-query", () => ({
  queryOptions: (options: unknown) => options,
  useSuspenseQueries: ({
    queries,
  }: {
    queries: { queryFn: () => unknown; queryKey: unknown }[]
  }) => {
    if (queries[0]?.queryKey && (queries[0].queryKey as unknown[]).includes("auth")) {
      return [{ data: { is_super_admin: state.superAdmin } }, { data: { folders: state.folders } }]
    }
    state.queries = queries.map((query) => query.queryKey)
    return queries.map(() => ({ data: { files: state.files, total: state.files.length } }))
  },
}))
vi.mock("@/features/workspaces/components/use-active-workspace", () => ({
  useActiveWorkspace: () => ({
    workspace: {
      name: "Example Organisation",
      slug: "example",
      current_user_role: state.role,
    },
  }),
}))
vi.mock("@/components/ui/tabs", () => {
  const part = ({ children }: PropsWithChildren) => createElement("div", null, children)
  return { Tabs: part, TabsList: part, TabsTrigger: part }
})
vi.mock("@/features/files/components/file-drop-zone", () => ({
  FileDropZone: ({ children }: PropsWithChildren) =>
    createElement("div", { "data-drop-zone": true }, children),
}))
vi.mock("@/features/files/components/file-upload-button", () => ({
  FileUploadButton: ({ scope = "workspace" }: { scope?: string }) =>
    createElement("button", null, `Upload ${scope}`),
}))
vi.mock("@/features/files/components/new-folder-button", () => ({
  NewFolderButton: () => "New Folder",
}))
vi.mock("@/features/files/components/folder-header", () => ({
  FolderHeader: () => "Folder actions",
}))
vi.mock("@/features/files/components/file-detail-modal", () => ({ FileDetailModal: () => null }))
vi.mock("@/features/files/components/files-table", () => ({
  FilesTable: (props: Record<string, unknown>) => {
    state.tableProps = props
    return "Files table"
  },
}))

beforeEach(() => {
  state.files = []
  state.folder = undefined
  state.folders = []
  state.page = undefined
  state.q = undefined
  state.scope = "platform"
  state.superAdmin = true
  state.role = "member"
  state.queries = []
  state.tableProps = null
})

it("places super-admin uploads in the Shared tab and searches shared files", () => {
  state.q = "report"
  const html = renderToStaticMarkup(createElement(FilesRoute))
  expect(html).toContain("Upload platform")
  expect(html).toContain('aria-label="Search files"')
  expect(state.queries[0]).toContain("platform-files")
  const params = (state.queries[0] as unknown[]).at(-1) as Record<string, unknown>
  expect(params["search"]).toBe("report")
  expect(html).toContain("become available in every workspace after processing")
  expect(html).not.toContain("New Folder")
  expect(html).not.toContain("Upload workspace")
  expect(html).not.toContain("data-drop-zone")
})

it.each(["read_only", null] as const)(
  "keeps folders visible without edit controls for %s",
  (role) => {
    state.role = role
    state.scope = "all"
    state.folders = [{ id: "folder-1", name: "Launch pack", description: null }]
    const html = renderToStaticMarkup(createElement(FilesRoute))
    expect(html).not.toContain("Upload workspace")
    expect(html).not.toContain("New Folder")
    expect(html).not.toContain("data-drop-zone")
    expect(state.tableProps?.["canEdit"]).toBe(false)
    expect(state.tableProps?.["emptyAction"]).toBeUndefined()
    expect(state.tableProps?.["entries"]).toEqual([{ folder: state.folders[0], kind: "folder" }])
  }
)

it("retains platform upload authority for a read-only super admin", () => {
  state.role = "read_only"
  const html = renderToStaticMarkup(createElement(FilesRoute))
  expect(html).toContain("Upload platform")
  expect(state.queries[0]).toContain("platform-files")
})

it("keeps ordinary members on published shared reads without upload controls", () => {
  state.superAdmin = false
  const html = renderToStaticMarkup(createElement(FilesRoute))
  expect(html).not.toContain("Upload platform")
  expect(html).not.toContain("Upload workspace")
  expect(html).toContain("Shared files are available in every workspace.")
  expect(html).toContain("Search files")
  expect(state.queries[0]).toContain("files")
  expect(state.queries[0]).not.toContain("platform-files")
})

it("labels the scope tabs with the workspace name and Shared", () => {
  state.scope = "all"
  const html = renderToStaticMarkup(createElement(FilesRoute))
  expect(html).toContain(">All<")
  expect(html).toContain("Example Organisation")
  expect(html).toContain(">Shared<")
  expect(html).not.toContain(">Workspace<")
  expect(html).not.toContain(">Platform<")
})

it("keeps uploads workspace-owned in the All tab and lists folders in the table", () => {
  state.scope = "all"
  state.folders = [{ id: "folder-1", name: "Launch pack", description: null }]
  const html = renderToStaticMarkup(createElement(FilesRoute))
  expect(html).toContain("Upload workspace")
  expect(html).toContain("New Folder")
  expect(html).toContain("data-drop-zone")
  expect(html).toContain("Drop files anywhere on this page")
  expect(html).not.toContain("Upload platform")
  expect(state.queries[0]).toContain("files")
  expect(state.tableProps?.["folders"]).toEqual(state.folders)
  expect(state.tableProps?.["entries"]).toEqual([{ folder: state.folders[0], kind: "folder" }])
  expect(state.tableProps?.["inFolder"]).toBe(false)
})

it("searches across folders and hides folder rows while a query is active", () => {
  state.scope = "all"
  state.q = "launch"
  state.folders = [{ id: "folder-1", name: "Launch pack", description: null }]
  renderToStaticMarkup(createElement(FilesRoute))
  const listKey = state.queries[0] as unknown[]
  const params = listKey.at(-1) as Record<string, unknown>
  expect(params["search"]).toBe("launch")
  expect(params["rootOnly"]).toBeUndefined()
  expect(state.tableProps?.["entries"]).toEqual([])
  expect(state.tableProps?.["emptyTitle"]).toBe("No matching files")
})

it("shows the folder view with a way back and scopes the list to that folder", () => {
  state.scope = "all"
  state.folder = "folder-1"
  state.folders = [{ id: "folder-1", name: "Launch pack", description: "Launch collateral" }]
  const html = renderToStaticMarkup(createElement(FilesRoute))
  expect(html).toContain("All files")
  expect(html).toContain("Launch pack")
  expect(html).toContain("Launch collateral")
  expect(html).toContain("Folder actions")
  expect(html).not.toContain(">Shared<")
  const listKey = state.queries[0] as unknown[]
  const params = listKey.at(-1) as Record<string, unknown>
  expect(params["folderId"]).toBe("folder-1")
  expect(state.tableProps?.["inFolder"]).toBe(true)
  expect(state.tableProps?.["emptyTitle"]).toBe("This folder is empty")
})

it("fetches enough files to fill a page once folders are merged in, and sizes the pager by both", () => {
  state.scope = "all"
  state.page = 2
  state.folders = Array.from({ length: 12 }, (_, index) => ({
    id: `folder-${String(index + 1)}`,
    name: `Folder ${String(index + 1)}`,
    description: null,
    updated_at: `2026-08-${String(index + 1).padStart(2, "0")}T00:00:00Z`,
  }))
  renderToStaticMarkup(createElement(FilesRoute))
  const listKey = state.queries[0] as unknown[]
  const params = listKey.at(-1) as Record<string, unknown>
  expect(params["limit"]).toBe(20)
  expect(params["offset"]).toBe(0)
  const entries = state.tableProps?.["entries"] as { folder: { id: string } }[]
  expect(entries.map((entry) => entry.folder.id)).toEqual(["folder-2", "folder-1"])
  expect(state.tableProps?.["offset"]).toBe(10)
  expect(state.tableProps?.["total"]).toBe(12)
})

it("splits large merged file windows into requests within the API limit", () => {
  state.scope = "all"
  state.page = 12
  state.folders = Array.from({ length: 105 }, (_, index) => ({
    id: `folder-${String(index)}`,
    name: `Folder ${String(index)}`,
    description: null,
  }))
  renderToStaticMarkup(createElement(FilesRoute))
  expect(state.queries.map((key) => (key as unknown[]).at(-1))).toEqual([
    expect.objectContaining({ limit: 100, offset: 5 }),
    expect.objectContaining({ limit: 15, offset: 105 }),
  ])
})
