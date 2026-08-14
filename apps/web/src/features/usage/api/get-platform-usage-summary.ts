// apps/web/src/features/usage/api/get-platform-usage-summary.ts

import { keepPreviousData, queryOptions, useQuery } from "@tanstack/react-query"

import { platformUsageQueryKeys } from "@/features/usage/api/query-keys"
import type { UsageRange, UsageSummary } from "@/features/usage/types"
import { apiRequest } from "@/lib/api/client"

async function getPlatformUsageSummary(range: UsageRange) {
  return apiRequest<UsageSummary>("/platform-usage/summary", {
    query: { from: range.from, to: range.to },
  })
}

export function platformUsageSummaryQueryOptions(userId: string, range: UsageRange) {
  return queryOptions({
    queryKey: platformUsageQueryKeys.summary(userId, range),
    queryFn: () => getPlatformUsageSummary(range),
    placeholderData: keepPreviousData,
    staleTime: 30_000,
  })
}

export function usePlatformUsageSummaryQuery(userId: string, range: UsageRange) {
  return useQuery(platformUsageSummaryQueryOptions(userId, range))
}
