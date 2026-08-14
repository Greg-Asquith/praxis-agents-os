// apps/web/src/features/usage/api/get-platform-usage-breakdown.ts

import { keepPreviousData, queryOptions, useQuery } from "@tanstack/react-query"

import { platformUsageQueryKeys } from "@/features/usage/api/query-keys"
import type {
  PlatformUsageBreakdown,
  PlatformUsageDimension,
  UsageRange,
} from "@/features/usage/types"
import { apiRequest } from "@/lib/api/client"

export type PlatformUsageBreakdownParams = UsageRange & {
  dimension: PlatformUsageDimension
}

async function getPlatformUsageBreakdown(params: PlatformUsageBreakdownParams) {
  return apiRequest<PlatformUsageBreakdown>("/platform-usage/breakdown", {
    query: { dimension: params.dimension, from: params.from, to: params.to },
  })
}

export function platformUsageBreakdownQueryOptions(
  userId: string,
  params: PlatformUsageBreakdownParams
) {
  return queryOptions({
    queryKey: platformUsageQueryKeys.breakdown(userId, params),
    queryFn: () => getPlatformUsageBreakdown(params),
    placeholderData: keepPreviousData,
    staleTime: 30_000,
  })
}

export function usePlatformUsageBreakdownQuery(
  userId: string,
  params: PlatformUsageBreakdownParams
) {
  return useQuery(platformUsageBreakdownQueryOptions(userId, params))
}
