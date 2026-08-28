// apps/web/src/features/knowledge/api/search-integration-sources.ts

import { queryOptions, useQuery } from "@tanstack/react-query"

import { knowledgeQueryKeys } from "@/features/knowledge/api/list-documents"
import type { KbIntegrationSourceSearchResult } from "@/features/knowledge/types"
import { apiRequest } from "@/lib/api/client"

export type SearchIntegrationSourcesRequest = {
  integrationResourceId: string
  query: string
  limit?: number
}

export function searchIntegrationSourcesQueryOptions(
  request: SearchIntegrationSourcesRequest | null
) {
  const params = {
    integrationResourceId: request?.integrationResourceId ?? "",
    limit: request?.limit ?? 20,
    query: request?.query.trim() ?? "",
  }
  return queryOptions({
    queryKey: knowledgeQueryKeys.integrationSourceSearch(params),
    queryFn: () =>
      apiRequest<KbIntegrationSourceSearchResult[]>("/kb/integration-sources/search", {
        query: {
          integration_resource_id: params.integrationResourceId,
          limit: params.limit,
          query: params.query || undefined,
        },
      }),
    enabled: request !== null,
    staleTime: 15_000,
  })
}

export function useIntegrationSourceSearchQuery(request: SearchIntegrationSourcesRequest | null) {
  return useQuery(searchIntegrationSourcesQueryOptions(request))
}
