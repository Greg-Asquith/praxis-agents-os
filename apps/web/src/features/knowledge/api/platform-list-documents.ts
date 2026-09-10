// apps/web/src/features/knowledge/api/platform-list-documents.ts

import { queryOptions } from "@tanstack/react-query"
import { hasActiveProcessing } from "@/features/knowledge/status"
import type { KbDocumentsListResponse } from "@/features/knowledge/types"
import { apiRequest } from "@/lib/api/client"
import { createWorkspaceScopedQueryKeys } from "@/lib/workspace"

export const platformKnowledgeQueryKeys = createWorkspaceScopedQueryKeys("platform-knowledge")

export function platformDocumentsQueryOptions({
  offset = 0,
  limit = 25,
}: { offset?: number; limit?: number } = {}) {
  return queryOptions({
    queryKey: platformKnowledgeQueryKeys.list({ offset, limit }),
    queryFn: () =>
      apiRequest<KbDocumentsListResponse>("/kb/platform/documents/", { query: { offset, limit } }),
    staleTime: 0,
    refetchInterval: (query) =>
      query.state.data && hasActiveProcessing(query.state.data.documents) ? 5_000 : false,
  })
}
