// apps/web/src/features/usage/api/get-usage-summary.ts

import { keepPreviousData, queryOptions, useQuery } from "@tanstack/react-query"

import { usageQueryKeys } from "@/features/usage/api/query-keys"
import type { UsageRange, UsageSummary } from "@/features/usage/types"
import { apiRequest } from "@/lib/api/client"

async function getUsageSummary(range: UsageRange) {
  return apiRequest<UsageSummary>("/usage/summary", {
    query: { from: range.from, to: range.to },
  })
}

export function usageSummaryQueryOptions(range: UsageRange) {
  return queryOptions({
    queryKey: usageQueryKeys.summary(range),
    queryFn: () => getUsageSummary(range),
    placeholderData: keepPreviousData,
    staleTime: 30_000,
  })
}

export function useUsageSummaryQuery(range: UsageRange) {
  return useQuery(usageSummaryQueryOptions(range))
}
