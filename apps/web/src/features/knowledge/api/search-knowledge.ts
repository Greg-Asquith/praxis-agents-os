// apps/web/src/features/knowledge/api/search-knowledge.ts

import { keepPreviousData, queryOptions, useQuery } from "@tanstack/react-query"

import { knowledgeQueryKeys } from "@/features/knowledge/api/list-documents"
import type { KbSearchResponse } from "@/features/knowledge/types"
import { apiRequest } from "@/lib/api/client"

function searchKnowledgeQueryOptions(query: string) {
  return queryOptions({
    queryKey: knowledgeQueryKeys.search(query),
    queryFn: () =>
      apiRequest<KbSearchResponse>("/kb/search", {
        body: { query, top_k: 20 },
        method: "POST",
      }),
    enabled: query.trim() !== "",
    placeholderData: keepPreviousData,
  })
}

export function useKnowledgeSearchQuery(query: string) {
  return useQuery(searchKnowledgeQueryOptions(query))
}
