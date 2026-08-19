// apps/web/src/features/tools/api/list-tool-catalog.ts

import { queryOptions, useSuspenseQuery } from "@tanstack/react-query"

import { toolsQueryKeys } from "@/features/tools/api/query-keys"
import type { ToolCatalogResponse } from "@/features/tools/types"
import { apiRequest } from "@/lib/api/client"

async function listToolCatalog() {
  return apiRequest<ToolCatalogResponse>("/tools/catalog")
}

function toolCatalogQueryOptions() {
  return queryOptions({
    queryKey: toolsQueryKeys.catalog(),
    queryFn: listToolCatalog,
    staleTime: 60_000,
  })
}

export function useToolCatalogQuery() {
  return useSuspenseQuery(toolCatalogQueryOptions())
}
