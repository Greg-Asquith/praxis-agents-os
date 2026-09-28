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
