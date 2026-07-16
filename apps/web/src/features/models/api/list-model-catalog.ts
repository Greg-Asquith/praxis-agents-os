// apps/web/src/features/models/api/list-model-catalog.ts

import { queryOptions, useSuspenseQuery } from "@tanstack/react-query"

import type { ModelCatalogResponse } from "@/features/models/types"
import { apiRequest } from "@/lib/api/client"

const modelCatalogQueryKey = ["models", "catalog"] as const

async function listModelCatalog() {
  return apiRequest<ModelCatalogResponse>("/models/catalog")
}

export function modelCatalogQueryOptions() {
  return queryOptions({
    queryKey: modelCatalogQueryKey,
    queryFn: listModelCatalog,
    staleTime: 60_000,
  })
}

export function useModelCatalogQuery() {
  return useSuspenseQuery(modelCatalogQueryOptions())
}
