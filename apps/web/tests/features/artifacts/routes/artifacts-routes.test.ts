// apps/web/tests/features/artifacts/routes/artifacts-routes.test.ts

import { createElement, type PropsWithChildren } from "react"
import { renderToStaticMarkup } from "react-dom/server"
import { beforeEach, describe, expect, it, vi } from "vitest"

import { ArtifactDetailRoute } from "@/features/artifacts/routes/artifact-detail-route"
import { ArtifactsRoute } from "@/features/artifacts/routes/artifacts-route"
import type { WorkspaceRole } from "@/features/workspaces/types"

const state = vi.hoisted<{
  detail: Record<string, unknown>
  queries: readonly unknown[][]
  role: WorkspaceRole | null
  search: Record<string, unknown>
  superAdmin: boolean
  table: Record<string, unknown>
}>(() => ({ detail: {}, queries: [], role: "member", search: {}, superAdmin: false, table: {} }))

vi.mock("@tanstack/react-router", () => ({
  useNavigate: () => vi.fn(),
  useParams: () => ({ artifactId: "artifact" }),
  useSearch: () => state.search,
}))
vi.mock("@tanstack/react-query", () => ({
  queryOptions: (options: unknown) => options,
  useSuspenseQuery: () => ({ data: { id: "user", is_super_admin: state.superAdmin } }),
  useSuspenseQueries: ({ queries }: { queries: { queryKey: unknown[] }[] }) =>
    queries.map(({ queryKey }) => {
      state.queries = [...state.queries, queryKey]
      return { data: { items: [], total: 0, limit: 25, offset: 0 } }
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
vi.mock("@/features/artifacts/components/artifacts-table", () => ({
  ArtifactsTable: (props: Record<string, unknown>) => {
    state.table = props
    return "Artifacts table"
  },
}))
vi.mock("@/features/artifacts/components/artifact-detail", () => ({
  ArtifactDetail: (props: Record<string, unknown>) => {
    state.detail = props
    return "Artifact detail"
  },
}))

beforeEach(() => {
  state.detail = {}
  state.queries = []
  state.role = "member"
  state.search = {}
  state.superAdmin = false
  state.table = {}
})

describe("Artifacts list authority", () => {
  it("matches the Files and Knowledge scope labels and searches workspace-visible artifacts", () => {
    const html = renderToStaticMarkup(createElement(ArtifactsRoute))

    expect(html).toContain(">All<")
    expect(html).toContain("Example Organisation")
    expect(html).toContain(">Shared<")
    expect(html).toContain('aria-label="Search artifacts"')
    expect(state.queries[0]).toContain("artifacts")
    expect(state.queries[0]?.at(-1)).toEqual({
      limit: 25,
      offset: 0,
      sortBy: "updated_at",
      sortDirection: "desc",
    })
    expect(state.table).toMatchObject({ management: false, sortBy: "updated_at", total: 0 })
  })

  it("filters published shared reads for ordinary members with the URL state", () => {
    state.search = { direction: "asc", page: 3, q: "policy", scope: "platform", sort: "title" }
    const html = renderToStaticMarkup(createElement(ArtifactsRoute))

    expect(html).toContain("make a workspace copy")
    expect(state.queries[0]).toContain("artifacts")
    expect(state.queries[0]?.at(-1)).toEqual({
      limit: 25,
      offset: 50,
      scope: "platform",
      search: "policy",
      sortBy: "title",
      sortDirection: "asc",
    })
    expect(state.table).toMatchObject({
      emptyTitle: "No matching artifacts",
      management: false,
      offset: 50,
    })
  })

  it("shows super admins the management list, including withdrawn artifacts", () => {
    state.role = "read_only"
    state.search = { q: "policy", scope: "platform" }
    state.superAdmin = true
    const html = renderToStaticMarkup(createElement(ArtifactsRoute))

    expect(html).toContain("Withdrawn artifacts stay listed here")
    expect(html).not.toContain('aria-label="Search artifacts"')
    expect(state.queries[0]).toContain("platform-artifacts")
    expect(state.queries[0]?.at(-1)).toEqual({ limit: 25, offset: 0 })
    expect(state.table).toMatchObject({ emptyTitle: "No shared artifacts", management: true })
  })

  it("keeps super admins on the tenant list outside the Shared tab", () => {
    state.superAdmin = true
    renderToStaticMarkup(createElement(ArtifactsRoute))

    expect(state.queries[0]).toContain("artifacts")
    expect(state.queries[0]).not.toContain("platform-artifacts")
  })
})

describe("Artifact detail authority", () => {
  it("ignores a management URL flag for ordinary members", () => {
    state.search = { platform: true, edit: true }
    renderToStaticMarkup(createElement(ArtifactDetailRoute))

    expect(state.detail).toMatchObject({
      artifactId: "artifact",
      isSuperAdmin: false,
      management: false,
      openEditor: true,
    })
  })

  it("enables the management read path for super admins who ask for it", () => {
    state.superAdmin = true
    state.search = { platform: true }
    renderToStaticMarkup(createElement(ArtifactDetailRoute))

    expect(state.detail).toMatchObject({ isSuperAdmin: true, management: true, openEditor: false })
    state.search = {}
    renderToStaticMarkup(createElement(ArtifactDetailRoute))
    expect(state.detail).toMatchObject({ isSuperAdmin: true, management: false })
  })
})
