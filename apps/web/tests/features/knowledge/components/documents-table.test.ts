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

    expect(html.match(/>Synced</g)).toHaveLength(2)
    expect(html.match(/>Refresh</g)).toHaveLength(2)
    expect(html).not.toContain(">Reprocess<")
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

function renderDocuments(documents: KbDocument[]) {
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
        children: createElement(DocumentsTable, { canWrite: true, documents }),
        router,
      })
    )
  )
}
