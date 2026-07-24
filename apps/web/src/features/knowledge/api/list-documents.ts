// apps/web/src/features/knowledge/api/list-documents.ts

import { queryOptions, useSuspenseQuery } from "@tanstack/react-query"

import { hasActiveProcessing } from "@/features/knowledge/status"
import type { KbDocumentsListResponse, ListKbDocumentsParams } from "@/features/knowledge/types"
import { apiRequest } from "@/lib/api/client"
import { createWorkspaceScopedQueryKeys } from "@/lib/workspace"

const baseKnowledgeQueryKeys = createWorkspaceScopedQueryKeys("knowledge")

export const knowledgeQueryKeys = {
  ...baseKnowledgeQueryKeys,
  searches: () => [...baseKnowledgeQueryKeys.workspace(), "search"] as const,
  search: (query: string) => [...baseKnowledgeQueryKeys.workspace(), "search", query] as const,
}

async function listDocuments({
  isPrivate,
  limit = 100,
  offset = 0,
  sourceType,
  status,
}: ListKbDocumentsParams = {}) {
  return apiRequest<KbDocumentsListResponse>("/kb/documents", {
    query: {
      is_private: isPrivate,
      limit,
      offset,
      source_type: sourceType,
      status,
    },
  })
}

function documentsQueryOptions(params: ListKbDocumentsParams = {}) {
  return queryOptions({
    queryKey: knowledgeQueryKeys.list(params),
    queryFn: () => listDocuments(params),
    refetchInterval: (query) =>
      query.state.data && hasActiveProcessing(query.state.data.documents) ? 5_000 : false,
    staleTime: 15_000,
  })
}

export function useDocumentsQuery(params: ListKbDocumentsParams = {}) {
  return useSuspenseQuery(documentsQueryOptions(params))
}
