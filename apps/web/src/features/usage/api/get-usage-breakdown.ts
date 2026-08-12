// apps/web/src/features/usage/api/get-usage-breakdown.ts

import { keepPreviousData, queryOptions, useQuery } from "@tanstack/react-query"

import { usageQueryKeys } from "@/features/usage/api/query-keys"
import type { UsageBreakdown, UsageDimension, UsageRange } from "@/features/usage/types"
import { apiRequest } from "@/lib/api/client"

export type UsageBreakdownParams = UsageRange & { dimension: UsageDimension }

async function getUsageBreakdown(params: UsageBreakdownParams) {
  return apiRequest<UsageBreakdown>("/usage/breakdown", {
    query: { dimension: params.dimension, from: params.from, to: params.to },
  })
}

export function usageBreakdownQueryOptions(params: UsageBreakdownParams) {
  return queryOptions({
    queryKey: usageQueryKeys.breakdown(params),
    queryFn: () => getUsageBreakdown(params),
    placeholderData: keepPreviousData,
    staleTime: 30_000,
  })
}

export function useUsageBreakdownQuery(params: UsageBreakdownParams) {
  return useQuery(usageBreakdownQueryOptions(params))
}
