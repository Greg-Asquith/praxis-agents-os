// apps/web/src/features/usage/api/get-model-pricing.ts

import { queryOptions, useQuery } from "@tanstack/react-query"

import { usageQueryKeys } from "@/features/usage/api/query-keys"
import type { ModelPricing } from "@/features/usage/types"
import { apiRequest } from "@/lib/api/client"

function modelPricingQueryOptions() {
  return queryOptions({
    queryKey: usageQueryKeys.pricing(),
    queryFn: () => apiRequest<ModelPricing>("/usage/model-pricing"),
    staleTime: 60_000,
  })
}

export function useModelPricingQuery(enabled: boolean) {
  return useQuery({ ...modelPricingQueryOptions(), enabled })
}
