import { createElement } from "react"
import { renderToStaticMarkup } from "react-dom/server"
import {
  createMemoryHistory,
  createRootRoute,
  createRoute,
  createRouter,
  RouterContextProvider,
} from "@tanstack/react-router"
import { describe, expect, it } from "vitest"

import { ArtifactsTable } from "@/features/artifacts/components/artifacts-table"
import type { ArtifactSummary } from "@/features/artifacts/types"

const artifact: ArtifactSummary = {
  agent_id: "agent-1",
  artifact_type: "markdown",
  conversation_id: "conversation-1",
  created_at: "2026-08-12T09:00:00Z",
  current_version_id: "version-2",
  id: "artifact-1",
  run_id: "run-1",
  title: "Launch brief",
  updated_at: "2026-08-12T10:30:00Z",
  version_count: 2,
  workspace_id: "workspace-1",
}

describe("ArtifactsTable", () => {
  it("renders the app-table headers and artifact link cells", () => {
    const html = renderArtifacts([artifact])

    expect(html).toContain("<th")
    expect(html).toContain(">Artifact<")
    expect(html).toContain(">Type<")
    expect(html).toContain(">Versions<")
    expect(html).toContain(">Updated<")
    expect(html).toContain('aria-sort="descending"')
    expect(html).toContain('href="/artifacts/artifact-1"')
    expect(html.match(/Launch brief/g)).toHaveLength(2)
    expect(html).toContain("Markdown")
    expect(html).toContain("<dl")
  })

  it("renders search, sorting, and pagination controls", () => {
    const artifacts = Array.from({ length: 12 }, (_, index) => ({
      ...artifact,
      id: `artifact-${String(index + 1)}`,
      title: `Artifact ${String(index + 1)}`,
    }))
    const html = renderArtifacts(artifacts)

    expect(html).toContain('href="/artifacts/artifact-12"')
    expect(html).toContain("Artifact 12")
    expect(html).toContain('aria-label="Search artifacts"')
    expect(html).toContain("Sort: Updated")
    expect(html).toContain("Showing 1-12 of 12")
  })

  it("keeps the existing empty state", () => {
    const html = renderArtifacts([])

    expect(html).toContain("No artifacts yet")
    expect(html).toContain(
      "Artifacts created by agents will appear here with their complete version history."
    )
    expect(html).not.toContain("<table")
  })
})

function renderArtifacts(artifacts: ArtifactSummary[]) {
  const rootRoute = createRootRoute()
  const artifactRoute = createRoute({
    getParentRoute: () => rootRoute,
    path: "/artifacts/$artifactId",
  })
  const router = createRouter({
    history: createMemoryHistory({ initialEntries: ["/"] }),
    routeTree: rootRoute.addChildren([artifactRoute]),
  })

  return renderToStaticMarkup(
    createElement(RouterContextProvider, {
      children: createElement(ArtifactsTable, {
        artifacts,
        globalFilter: "",
        isChangingView: false,
        onGlobalFilterChange: () => undefined,
        onPaginationChange: () => undefined,
        onSortingChange: () => undefined,
        pagination: { pageIndex: 0, pageSize: 25 },
        sorting: [{ id: "updated_at", desc: true }],
        total: artifacts.length,
      }),
      router,
    })
  )
}
