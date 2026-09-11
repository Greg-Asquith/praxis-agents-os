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
import { platformArtifactQueryOptions } from "@/features/artifacts/api/platform-get-artifact"
import { platformArtifactVersionContentQueryOptions } from "@/features/artifacts/api/platform-get-artifact-version-content"
import { ArtifactDetail } from "@/features/artifacts/components/artifact-detail"
import type { Artifact, ArtifactContent, PlatformArtifact } from "@/features/artifacts/types"
import { ActiveWorkspaceContext } from "@/features/workspaces/components/active-workspace-context"
import type { Workspace } from "@/features/workspaces/types"

vi.mock("@/features/artifacts/api/list-artifact-shares", () => ({
  useArtifactSharesQuery: vi.fn(() => ({ data: { items: [] } })),
}))

const EDITOR_ROLES = new Set<Workspace["current_user_role"]>(["owner", "admin", "member"])

const artifact: PlatformArtifact = {
  id: "artifact",
  scope: "platform",
  workspace_id: null,
  is_published: true,
  can_manage_platform: false,
  can_edit: false,
  published_version_id: "version-2",
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
  name: "Example Organisation",
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

type RenderOptions = {
  artifact?: Partial<PlatformArtifact>
  isSuperAdmin?: boolean
  management?: boolean
  role: Workspace["current_user_role"]
  scope?: Artifact["scope"]
}

function renderDetail({
  artifact: overrides = {},
  isSuperAdmin = false,
  management = false,
  role,
  scope = "platform",
}: RenderOptions) {
  const target: PlatformArtifact = {
    ...artifact,
    scope,
    workspace_id: scope === "workspace" ? workspace.id : null,
    can_edit: EDITOR_ROLES.has(role) && (scope === "workspace" || artifact.is_published),
    ...overrides,
  }
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  const detailOptions = management ? platformArtifactQueryOptions : artifactQueryOptions
  const contentOptions = management
    ? platformArtifactVersionContentQueryOptions
    : artifactVersionContentQueryOptions
  client.setQueryData(detailOptions(target.id).queryKey, target)
  for (const version of target.versions) {
    client.setQueryData(contentOptions(target.id, version.id).queryKey, content)
  }
  const rootRoute = createRootRoute()
  const router = createRouter({
    history: createMemoryHistory({ initialEntries: ["/"] }),
    routeTree: rootRoute.addChildren([
      createRoute({ getParentRoute: () => rootRoute, path: "/artifacts" }),
      createRoute({ getParentRoute: () => rootRoute, path: "/artifacts/$artifactId" }),
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
          children: createElement(ArtifactDetail, {
            artifactId: target.id,
            isSuperAdmin,
            management,
          }),
        }),
      }),
    })
  )
}

describe("ArtifactDetail", () => {
  it.each(["read_only", null] as const)(
    "renders a read-only shared preview for role %s without copies, edits, or shares",
    (role) => {
      const html = renderDetail({ role })

      expect(html).toContain(">Shared<")
      expect(html).toContain("Available in every workspace on this deployment")
      expect(html).toContain("You can view and open this artifact.")
      expect(html).toContain('title="Shared report preview"')
      expect(html).toContain('sandbox="allow-scripts"')
      expect(html).toContain('aria-label="Artifact version"')
      expect(html).toContain('aria-label="Open artifact Shared report"')
      expect(html).not.toContain("Edit</button>")
      expect(html).not.toContain("Make a workspace copy")
      expect(html).not.toContain("Publish to platform")
      expect(html).not.toContain(">Withdraw<")
      expect(html).not.toContain("Share Links")
      expect(useArtifactSharesQuery).not.toHaveBeenCalled()
    }
  )

  it.each(["owner", "admin", "member"] as const)(
    "lets %s edit a shared artifact for every workspace or copy it locally",
    (role) => {
      const html = renderDetail({ role })

      expect(html).toContain("Edit</button>")
      expect(html).toContain("Make a workspace copy")
      expect(html).toContain("updates it everywhere immediately")
      expect(html).toContain("stay in Example Organisation")
      expect(html).not.toContain("Share Links")
      expect(html).not.toContain(">Delete<")
      expect(useArtifactSharesQuery).not.toHaveBeenCalled()
    }
  )

  it("shows lifecycle controls to super admins on a published shared artifact", () => {
    const html = renderDetail({ role: "read_only", artifact: { can_manage_platform: true } })

    expect(html).toContain("Withdraw</button>")
    expect(html).toContain("Delete</button>")
    expect(html).not.toContain("Publish</button>")
    expect(html).not.toContain("Make a workspace copy")
  })

  it("reviews a withdrawn artifact through the management read path", () => {
    const html = renderDetail({
      artifact: { can_edit: true, can_manage_platform: true, is_published: false },
      isSuperAdmin: true,
      management: true,
      role: "read_only",
    })

    expect(html).toContain(">Withdrawn<")
    expect(html).toContain("Withdrawn from every workspace")
    expect(html).toContain("Publish</button>")
    expect(html).toContain("Edit</button>")
    expect(html).not.toContain('aria-label="Open artifact Shared report"')
    expect(html).not.toContain("Make a workspace copy")
  })

  it.each(["owner", "admin"] as const)("retains workspace editing and shares for %s", (role) => {
    const html = renderDetail({ role, scope: "workspace" })

    expect(html).toContain("Edit</button>")
    expect(html).toContain("Share Links")
    expect(html).not.toContain(">Shared<")
    expect(html).not.toContain("Publish to platform")
    expect(useArtifactSharesQuery).toHaveBeenCalledWith(artifact.id)
  })

  it("offers Publish to platform only to super admins on workspace artifacts", () => {
    const html = renderDetail({ role: "read_only", scope: "workspace", isSuperAdmin: true })

    expect(html).toContain("Publish to platform")
    expect(html).not.toContain("Edit</button>")
    expect(renderDetail({ role: "owner", isSuperAdmin: true })).not.toContain("Publish to platform")
  })

  it("lets workspace members edit without loading share management", () => {
    const html = renderDetail({ role: "member", scope: "workspace" })

    expect(html).toContain("Edit</button>")
    expect(html).not.toContain("Share Links")
    expect(useArtifactSharesQuery).not.toHaveBeenCalled()
  })

  it.each(["read_only", null] as const)("hides workspace mutations for role %s", (role) => {
    const html = renderDetail({ role, scope: "workspace" })

    expect(html).not.toContain("Edit</button>")
    expect(html).not.toContain("Share Links")
    expect(useArtifactSharesQuery).not.toHaveBeenCalled()
  })
})
