// apps/web/src/features/tools/api/list-tool-catalog.ts

import { queryOptions, useSuspenseQuery } from "@tanstack/react-query"

import type { ToolCatalogResponse } from "@/features/tools/types"
import { getActiveWorkspaceSlug } from "@/features/workspaces/workspace-context"
import { apiRequest } from "@/lib/api/client"

const toolsQueryKeys = {
  all: ["tools"] as const,
  workspace: () => [...toolsQueryKeys.all, activeWorkspaceQueryScope()] as const,
  catalog: () => [...toolsQueryKeys.workspace(), "catalog"] as const,
}

function activeWorkspaceQueryScope() {
  return getActiveWorkspaceSlug() ?? "__no_workspace__"
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
