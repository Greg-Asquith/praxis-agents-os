// apps/web/tests/features/knowledge/routes/knowledge-routes.test.ts

import { createElement, type PropsWithChildren } from "react"
import { renderToStaticMarkup } from "react-dom/server"
import { beforeEach, describe, expect, it, vi } from "vitest"
import { KnowledgeRoute } from "@/features/knowledge/routes/knowledge-route"
import { KnowledgeDocumentRoute } from "@/features/knowledge/routes/document-detail-route"
import type { WorkspaceRole } from "@/features/workspaces/types"

const state = vi.hoisted<{
  role: WorkspaceRole | null
  superAdmin: boolean
  search: Record<string, unknown>
  queries: readonly unknown[][]
  header: Record<string, unknown>
  table: Record<string, unknown>
  document: {
    id: string
    scope: string
    is_published: boolean
    can_manage_platform: boolean
    created_by_user_id: string
  }
}>(() => ({
  role: "member",
  superAdmin: false,
  search: {},
  queries: [],
  header: {},
  table: {},
  document: {
    id: "document",
    scope: "platform",
    is_published: true,
    can_manage_platform: true,
    created_by_user_id: "user",
  },
}))
vi.mock("@tanstack/react-router", () => ({
  useSearch: () => state.search,
  useParams: () => ({ documentId: "document" }),
  useNavigate: () => vi.fn(),
}))
vi.mock("@tanstack/react-query", () => ({
  queryOptions: (options: unknown) => options,
  useSuspenseQuery: () => ({ data: { id: "user", is_super_admin: state.superAdmin } }),
  useSuspenseQueries: ({ queries }: { queries: { queryKey: unknown[] }[] }) =>
    queries.map(({ queryKey }) => {
      state.queries = [...state.queries, queryKey]
      return { data: queryKey.includes("detail") ? state.document : { documents: [], total: 0 } }
    }),
}))
vi.mock("@/features/workspaces/components/use-active-workspace", () => ({
  useActiveWorkspace: () => ({
    workspace: { name: "Example Organisation", current_user_role: state.role },
  }),
}))
vi.mock("@/components/ui/tabs", () => {
  const part = ({ children }: PropsWithChildren) => createElement("div", null, children)
  return { Tabs: part, TabsList: part, TabsTrigger: part }
})
vi.mock("@/features/knowledge/components/add-document-menu", () => ({
  AddDocumentMenu: ({ platform }: { platform: boolean }) =>
    createElement("button", null, platform ? "Add platform" : "Add workspace"),
}))
vi.mock("@/features/knowledge/components/knowledge-search-panel", () => ({
  KnowledgeSearchPanel: () => "Search knowledge",
}))
vi.mock("@/features/knowledge/components/documents-table", () => ({
  DocumentsTable: (props: Record<string, unknown>) => {
    state.table = props
    return "Documents"
  },
}))
vi.mock("@/features/knowledge/components/document-detail-header", () => ({
  DocumentDetailHeader: (props: Record<string, unknown>) => {
    state.header = props
    return "Document header"
  },
}))
vi.mock("@/features/knowledge/components/document-markdown-view", () => ({
  DocumentMarkdownView: () => "Document content",
}))

beforeEach(() => {
  state.role = "member"
  state.superAdmin = false
  state.search = {}
  state.queries = []
  state.header = {}
  state.table = {}
  state.document = {
    id: "document",
    scope: "platform",
    is_published: true,
    can_manage_platform: true,
    created_by_user_id: "user",
  }
})

describe("Knowledge list authority", () => {
  it("matches Files scope labels and keeps All additions in the workspace", () => {
    state.superAdmin = true
    const html = renderToStaticMarkup(createElement(KnowledgeRoute))
    expect(html).toContain(">All<")
    expect(html).toContain("Example Organisation")
    expect(html).toContain(">Shared<")
    expect(html).toContain("Add workspace")
    expect(html).not.toContain("Add platform")
    expect(state.queries[0]).toContain("knowledge")
  })
  it("filters published shared reads for ordinary editors without management controls", () => {
    state.search = { scope: "platform", page: 3 }
    const html = renderToStaticMarkup(createElement(KnowledgeRoute))
    expect(html).not.toContain("Add platform")
    expect(html).not.toContain("Add workspace")
    expect(state.queries[0]).toContain("knowledge")
    expect(state.queries[0]?.at(-1)).toEqual({ scope: "platform", limit: 25, offset: 50 })
  })
  it("allows read-only super admins to manage shared drafts", () => {
    state.superAdmin = true
    state.role = "read_only"
    state.search = { scope: "platform" }
    const html = renderToStaticMarkup(createElement(KnowledgeRoute))
    expect(html).toContain("Add platform")
    expect(state.queries[0]).toContain("platform-knowledge")
    expect(state.table["canWrite"]).toBe(false)
  })
  it.each(["read_only", null] as const)("does not grant workspace authoring to %s", (role) => {
    state.role = role
    state.superAdmin = true
    state.search = { scope: "workspace" }
    const html = renderToStaticMarkup(createElement(KnowledgeRoute))
    expect(html).not.toContain("Add workspace")
    expect(state.table["canWrite"]).toBe(false)
  })
})

describe("Knowledge detail authority", () => {
  it("ignores a management URL flag for ordinary members", () => {
    state.search = { platform: true }
    renderToStaticMarkup(createElement(KnowledgeDocumentRoute))
    expect(state.queries[0]).toContain("knowledge")
    expect(state.queries[0]).not.toContain("platform-knowledge")
    expect(state.header).toMatchObject({
      canWrite: false,
      canMakePrivate: false,
      canCopy: true,
      canManagePlatform: false,
    })
  })
  it("retains super-admin management through a read-only membership", () => {
    state.search = { platform: true }
    state.superAdmin = true
    state.role = "read_only"
    renderToStaticMarkup(createElement(KnowledgeDocumentRoute))
    expect(state.queries[0]).toContain("platform-knowledge")
    expect(state.header).toMatchObject({ canWrite: false, canCopy: false, canManagePlatform: true })
  })
  it("requires the response management capability as well as super-admin access", () => {
    state.search = { platform: true }
    state.superAdmin = true
    state.document.can_manage_platform = false
    renderToStaticMarkup(createElement(KnowledgeDocumentRoute))
    expect(state.header["canManagePlatform"]).toBe(false)
  })
  it("keeps unpublished drafts from being copied", () => {
    state.superAdmin = true
    state.search = { platform: true }
    state.document.is_published = false
    renderToStaticMarkup(createElement(KnowledgeDocumentRoute))
    expect(state.header["canCopy"]).toBe(false)
  })
  it("preserves workspace editing and creator privacy controls", () => {
    state.document.scope = "workspace"
    renderToStaticMarkup(createElement(KnowledgeDocumentRoute))
    expect(state.header).toMatchObject({
      canWrite: true,
      canMakePrivate: true,
      canCopy: false,
      canManagePlatform: false,
    })
    state.document.created_by_user_id = "someone-else"
    renderToStaticMarkup(createElement(KnowledgeDocumentRoute))
    expect(state.header["canMakePrivate"]).toBe(false)
  })
})
