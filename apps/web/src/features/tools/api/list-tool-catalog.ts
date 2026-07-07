// apps/web/src/features/tools/api/list-tool-catalog.ts

import { queryOptions, useSuspenseQuery } from "@tanstack/react-query"

import type { ToolCatalogResponse } from "@/features/tools/types"
import { createWorkspaceScopedQueryKeys } from "@/features/workspaces/query-keys"
import { apiRequest } from "@/lib/api/client"

const baseToolsQueryKeys = createWorkspaceScopedQueryKeys("tools")

const toolsQueryKeys = {
  ...baseToolsQueryKeys,
  catalog: () => [...baseToolsQueryKeys.workspace(), "catalog"] as const,
}

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
