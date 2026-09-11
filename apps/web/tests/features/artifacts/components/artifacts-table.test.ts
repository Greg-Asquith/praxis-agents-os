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

import { ArtifactsTable, type ArtifactRow } from "@/features/artifacts/components/artifacts-table"
import type { ArtifactSummary } from "@/features/artifacts/types"

const artifact: ArtifactSummary = {
  agent_id: "agent-1",
  artifact_type: "markdown",
  can_edit: true,
  can_manage_platform: false,
  conversation_id: "conversation-1",
  created_at: "2026-08-12T09:00:00Z",
  current_version_id: "version-2",
  id: "artifact-1",
  is_published: false,
  scope: "workspace",
  run_id: "run-1",
  title: "Launch brief",
  updated_at: "2026-08-12T10:30:00Z",
  version_count: 2,
  workspace_id: "workspace-1",
}
const shared: ArtifactRow = {
  ...artifact,
  id: "artifact-2",
  is_published: true,
  scope: "platform",
  title: "Shared report",
  workspace_id: null,
}

describe("ArtifactsTable", () => {
  it("renders the app-table headers, type tiles, and detail links", () => {
    const html = renderArtifacts([artifact])

    expect(html).toContain("<th")
    expect(html).toContain(">Artifact<")
    expect(html).toContain(">Versions<")
    expect(html).toContain(">Updated<")
    expect(html).not.toContain(">Type<")
    expect(html).toContain('aria-sort="descending"')
    expect(html).toContain('href="/artifacts/artifact-1"')
    expect(html).toContain('data-artifact-type="markdown"')
    expect(html).toContain('aria-label="Open details for Launch brief"')
    expect(html).toContain('aria-label="Open Launch brief"')
    expect(html).toContain("Markdown")
    expect(html).toContain("Details")
  })

  it("renders sorting and pagination controls", () => {
    const artifacts = Array.from({ length: 12 }, (_, index) => ({
      ...artifact,
      id: `artifact-${String(index + 1)}`,
      title: `Artifact ${String(index + 1)}`,
    }))
    const html = renderArtifacts(artifacts)

    expect(html).toContain('href="/artifacts/artifact-12"')
    expect(html).toContain("Artifact 12")
    expect(html).toContain("Sort: Updated")
    expect(html).toContain("Showing 1-12 of 12")
  })

  it("identifies shared Artifacts in both table and mobile layouts", () => {
    const html = renderArtifacts([shared])

    expect(html.match(/>Shared</g)).toHaveLength(2)
    expect(html).toContain('href="/artifacts/artifact-2"')
    expect(html).not.toContain("platform=true")
    expect(renderArtifacts([artifact])).not.toContain(">Shared<")
  })

  it("labels publication state and drops open actions in the management list", () => {
    const withdrawn: ArtifactRow = {
      ...shared,
      id: "artifact-3",
      is_published: false,
      published_version_id: "version-1",
      title: "Withdrawn report",
    }
    const draft: ArtifactRow = {
      ...shared,
      id: "artifact-4",
      is_published: false,
      published_version_id: null,
      title: "Draft report",
    }
    const html = renderArtifacts([shared, withdrawn, draft], { management: true })

    expect(html.match(/>Withdrawn</g)).toHaveLength(2)
    expect(html.match(/>Unpublished</g)).toHaveLength(2)
    expect(html).toContain('href="/artifacts/artifact-3?platform=true"')
    expect(html).toContain('aria-label="Open Shared report"')
    expect(html).not.toContain('aria-label="Open Withdrawn report"')
    expect(html).not.toContain('aria-label="Open Draft report"')
    expect(html).not.toContain("Sort: Updated")
    expect(html).not.toContain('aria-sort="descending"')
  })

  it("keeps the default empty state and accepts scoped copy", () => {
    const html = renderArtifacts([])

    expect(html).toContain("No artifacts yet")
    expect(html).toContain(
      "Artifacts created by agents will appear here with their complete version history."
    )
    expect(html).not.toContain("<table")
    expect(renderArtifacts([], { emptyTitle: "No shared artifacts" })).toContain(
      "No shared artifacts"
    )
  })
})

function renderArtifacts(
  artifacts: ArtifactRow[],
  options: { emptyTitle?: string; management?: boolean } = {}
) {
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
        isChangingView: false,
        limit: 25,
        offset: 0,
        onOpenArtifact: () => undefined,
        onPageChange: () => undefined,
        onSortChange: () => undefined,
        sortBy: "updated_at",
        sortDirection: "desc",
        total: artifacts.length,
        ...options,
      }),
      router,
    })
  )
}
