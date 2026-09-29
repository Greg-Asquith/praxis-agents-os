// apps/web/src/features/models/api/list-model-catalog.ts

import { queryOptions, useSuspenseQuery } from "@tanstack/react-query"

import type { ModelCatalogResponse } from "@/features/models/types"
import { apiRequest } from "@/lib/api/client"
import { createWorkspaceScopedQueryKeys } from "@/lib/workspace"

// The catalog's default model follows the active workspace's default.
export const modelsQueryKeys = createWorkspaceScopedQueryKeys("models")

async function listModelCatalog() {
  return apiRequest<ModelCatalogResponse>("/models/catalog")
}

export function modelCatalogQueryOptions() {
  return queryOptions({
    queryKey: [...modelsQueryKeys.workspace(), "catalog"] as const,
    queryFn: listModelCatalog,
    staleTime: 60_000,
  })
}

export function useModelCatalogQuery() {
  return useSuspenseQuery(modelCatalogQueryOptions())
}
