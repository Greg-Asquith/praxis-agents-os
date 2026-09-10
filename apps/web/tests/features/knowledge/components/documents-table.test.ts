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
import { describe, expect, it } from "vitest"

import { DocumentsTable } from "@/features/knowledge/components/documents-table"
import type { KbDocument, KbSourceType } from "@/features/knowledge/types"

describe("DocumentsTable", () => {
  it("shows refresh controls and sync state only for refreshable sources", () => {
    const html = renderDocuments([
      document({ id: "url-document", sourceType: "url", syncStatus: "ready" }),
      document({ id: "manual-document", sourceType: "manual", syncStatus: null }),
    ])

    expect(html).not.toContain(">Synced<")
    expect(html.match(/>Ready</g)).toHaveLength(4)
    expect(html.match(/>Refresh</g)).toHaveLength(2)
    expect(html).not.toContain(">Reprocess<")
  })
  it("shows platform scope and publication in both layouts without workspace refresh actions", () => {
    const shared = {
      ...document({ id: "shared", sourceType: "manual", syncStatus: null }),
      scope: "platform" as const,
      workspace_id: null,
      is_published: true,
      can_manage_platform: true,
      status: "error" as const,
    }
    const html = renderDocuments([shared])
    expect(html.match(/>Platform</g)).toHaveLength(2)
    expect(html.match(/>Published</g)).toHaveLength(2)
    expect(html).not.toContain(">Reprocess<")
    expect(html).not.toContain(">Refresh<")
    const draft = renderDocuments([{ ...shared, is_published: false }])
    expect(draft.match(/>Unpublished</g)).toHaveLength(2)
  })

  it("shows one successful status and consistent privacy badges in both layouts", () => {
    const ready = document({ id: "ready", sourceType: "upload", syncStatus: null })
    const html = renderDocuments([
      { ...ready, scope: "platform", workspace_id: null, is_published: true },
      { ...ready, id: "workspace" },
      { ...ready, id: "private", is_private: true },
    ])
    expect(html.match(/>Published</g)).toHaveLength(2)
    expect(html.match(/>Ready</g)).toHaveLength(4)
    for (const label of ["Platform", "Workspace", "Private"]) {
      expect(
        html.match(
          new RegExp(`data-variant="outline"[^>]*>(?:<svg[\\s\\S]*?</svg>)?${label}<`, "g")
        )
      ).toHaveLength(2)
    }
  })

  it("keeps source refresh failures visible", () => {
    const html = renderDocuments([
      document({ id: "failed-sync", sourceType: "url", syncStatus: "error" }),
    ])
    expect(html.match(/>Refresh failed</g)).toHaveLength(2)
  })

  it("preserves workspace retry controls and hides them for read-only members", () => {
    const failed = {
      ...document({ id: "failed", sourceType: "manual", syncStatus: null }),
      status: "error" as const,
    }
    expect(renderDocuments([failed]).match(/>Reprocess</g)).toHaveLength(2)
    expect(renderDocuments([failed], false)).not.toContain(">Reprocess<")
  })
})

function document({
  id,
  sourceType,
  syncStatus,
}: {
  id: string
  sourceType: KbSourceType
  syncStatus: KbDocument["source_sync_status"]
}): KbDocument {
  return {
    scope: "workspace",
    workspace_id: "workspace",
    is_published: false,
    can_manage_platform: false,
    chunk_count: 1,
    created_at: "2026-09-01T09:00:00Z",
    created_by_user_id: "user-1",
    id,
    is_private: false,
    processing_attempts: 0,
    processing_error: null,
    source_sync_status: syncStatus,
    source_synced_at: syncStatus ? "2026-09-01T10:00:00Z" : null,
    source_type: sourceType,
    status: "ready",
    title: `${sourceType} document`,
    updated_at: "2026-09-01T10:00:00Z",
  }
}

function renderDocuments(documents: KbDocument[], canWrite = true) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  const rootRoute = createRootRoute()
  const documentRoute = createRoute({
    getParentRoute: () => rootRoute,
    path: "/knowledge/$documentId",
  })
  const router = createRouter({
    history: createMemoryHistory({ initialEntries: ["/"] }),
    routeTree: rootRoute.addChildren([documentRoute]),
  })

  return renderToStaticMarkup(
    createElement(
      QueryClientProvider,
      { client: queryClient },
      createElement(RouterContextProvider, {
        children: createElement(DocumentsTable, { canWrite, documents }),
        router,
      })
    )
  )
}
