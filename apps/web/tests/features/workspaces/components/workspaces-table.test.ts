import { createElement } from "react"
import { renderToStaticMarkup } from "react-dom/server"
import {
  createMemoryHistory,
  createRootRoute,
  createRoute,
  createRouter,
  RouterContextProvider,
} from "@tanstack/react-router"
import { describe, expect, it, vi } from "vitest"

import { WorkspacesTable } from "@/features/workspaces/components/workspaces-table"
import type { Workspace } from "@/features/workspaces/types"

const workspace: Workspace = {
  created_at: "2026-08-12T09:00:00Z",
  current_user_role: "owner",
  deleted: false,
  deleted_at: null,
  icon_url: null,
  id: "workspace-1",
  is_personal: true,
  name: "Personal workspace",
  slug: "personal",
  status: "active",
  updated_at: "2026-08-12T09:00:00Z",
}

vi.mock("@/features/workspaces/components/use-active-workspace", () => ({
  useActiveWorkspace: () => ({
    setWorkspaceBySlug: () => undefined,
    workspace,
    workspaces: [workspace],
  }),
}))

describe("WorkspacesTable", () => {
  it("does not repeat the Active badge for the current active workspace", () => {
    const html = renderWorkspaces()

    expect(html.match(/>Active</g)).toHaveLength(2)
    expect(html.match(/>Personal</g)).toHaveLength(2)
  })
})

function renderWorkspaces() {
  const rootRoute = createRootRoute()
  const settingsRoute = createRoute({
    getParentRoute: () => rootRoute,
    path: "/workspace-settings",
  })
  const router = createRouter({
    history: createMemoryHistory({ initialEntries: ["/"] }),
    routeTree: rootRoute.addChildren([settingsRoute]),
  })

  return renderToStaticMarkup(
    createElement(RouterContextProvider, {
      children: createElement(WorkspacesTable, { workspaces: [workspace] }),
      router,
    })
  )
}
