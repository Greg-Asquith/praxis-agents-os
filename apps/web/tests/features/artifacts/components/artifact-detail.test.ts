import { createElement } from "react"
import { renderToStaticMarkup } from "react-dom/server"
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import {
  createMemoryHistory,
  createRootRoute,
  createRoute,
  createRouter,
  RouterContextProvider,
} from "@tanstack/react-router"
import { beforeEach, describe, expect, it, vi } from "vitest"

import { artifactQueryOptions } from "@/features/artifacts/api/get-artifact"
import { artifactVersionContentQueryOptions } from "@/features/artifacts/api/get-artifact-version-content"
import { useArtifactSharesQuery } from "@/features/artifacts/api/list-artifact-shares"
import { ArtifactDetail } from "@/features/artifacts/components/artifact-detail"
import type { Artifact, ArtifactContent } from "@/features/artifacts/types"
import { ActiveWorkspaceContext } from "@/features/workspaces/components/active-workspace-context"
import type { Workspace } from "@/features/workspaces/types"

vi.mock("@/features/artifacts/api/list-artifact-shares", () => ({
  useArtifactSharesQuery: vi.fn(() => ({ data: { items: [] } })),
}))

const artifact: Artifact = {
  id: "artifact",
  scope: "platform",
  workspace_id: null,
  agent_id: null,
  conversation_id: null,
  run_id: null,
  current_version_id: "version-2",
  artifact_type: "html",
  title: "Shared report",
  created_at: "2026-09-10T10:00:00Z",
  updated_at: "2026-09-11T10:00:00Z",
  versions: [2, 1].map((number) => ({
    id: `version-${String(number)}`,
    created_at: "2026-09-10T10:00:00Z",
    created_by_user_id: null,
    created_by_agent_id: null,
    created_by_system: true,
    size_bytes: 21,
    revision_number: number,
    revision_kind: number === 1 ? "create" : "edit",
    restored_from_revision_id: null,
  })),
}
const content: ArtifactContent = {
  content: "<p>Shared content</p>",
  content_type: "text/html",
  size_bytes: 21,
  download_url: null,
}
const workspace: Workspace = {
  id: "workspace",
  slug: "example",
  name: "Example",
  icon_url: null,
  is_personal: false,
  status: "active",
  current_user_role: "owner",
  created_at: artifact.created_at,
  updated_at: artifact.updated_at,
  deleted: false,
  deleted_at: null,
}

beforeEach(() => vi.clearAllMocks())

function renderDetail(role: Workspace["current_user_role"], scope: Artifact["scope"] = "platform") {
  const target = { ...artifact, scope, workspace_id: scope === "workspace" ? workspace.id : null }
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  client.setQueryData(artifactQueryOptions(target.id).queryKey, target)
  for (const version of target.versions) {
    client.setQueryData(artifactVersionContentQueryOptions(target.id, version.id).queryKey, content)
  }
  const rootRoute = createRootRoute()
  const router = createRouter({
    history: createMemoryHistory({ initialEntries: ["/"] }),
    routeTree: rootRoute.addChildren([
      createRoute({ getParentRoute: () => rootRoute, path: "/artifacts" }),
    ]),
  })
  return renderToStaticMarkup(
    createElement(QueryClientProvider, {
      client,
      children: createElement(RouterContextProvider, {
        router,
        children: createElement(ActiveWorkspaceContext, {
          value: {
            workspace: { ...workspace, current_user_role: role },
            workspaces: [],
            setWorkspaceBySlug: () => undefined,
          },
          children: createElement(ArtifactDetail, { artifactId: target.id }),
        }),
      }),
    })
  )
}

describe("ArtifactDetail", () => {
  it.each(["owner", "admin", "member", "read_only"] as const)(
    "renders shared previews for %s without fetching anonymous shares or offering edits",
    (role) => {
      const html = renderDetail(role)

      expect(html).toContain(">Shared<")
      expect(html).toContain('title="Shared report preview"')
      expect(html).toContain('sandbox="allow-scripts"')
      expect(html).toContain('aria-label="Artifact version"')
      expect(html).toContain('aria-label="Open artifact Shared report"')
      expect(html).not.toContain(">Edit</button>")
      expect(html).not.toContain(">Restore</button>")
      expect(html).not.toContain("Share Links")
      expect(useArtifactSharesQuery).not.toHaveBeenCalled()
    }
  )

  it.each(["owner", "admin"] as const)("retains workspace editing and shares for %s", (role) => {
    const html = renderDetail(role, "workspace")

    expect(html).toContain("Edit</button>")
    expect(html).toContain("Share Links")
    expect(html).not.toContain(">Shared<")
    expect(useArtifactSharesQuery).toHaveBeenCalledWith(artifact.id)
  })

  it("lets workspace members edit without loading share management", () => {
    const html = renderDetail("member", "workspace")

    expect(html).toContain("Edit</button>")
    expect(html).not.toContain("Share Links")
    expect(useArtifactSharesQuery).not.toHaveBeenCalled()
  })

  it.each(["read_only", null] as const)("hides workspace mutations for role %s", (role) => {
    const html = renderDetail(role, "workspace")

    expect(html).not.toContain("Edit</button>")
    expect(html).not.toContain("Share Links")
    expect(useArtifactSharesQuery).not.toHaveBeenCalled()
  })
})
