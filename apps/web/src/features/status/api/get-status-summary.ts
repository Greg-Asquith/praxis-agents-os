// apps/web/src/features/status/api/get-status-summary.py

import { queryOptions, useSuspenseQuery } from "@tanstack/react-query"

import type { StatusSummary } from "@/features/status/types"
import { apiRequest } from "@/lib/api/client"
import { createWorkspaceScopedQueryKeys } from "@/lib/workspace"

const baseStatusQueryKeys = createWorkspaceScopedQueryKeys("status")

export const statusQueryKeys = {
  ...baseStatusQueryKeys,
  summary: () => [...baseStatusQueryKeys.workspace(), "summary"] as const,
}

async function getStatusSummary() {
  return apiRequest<StatusSummary>("/status/summary")
}

export function statusSummaryQueryOptions() {
  return queryOptions({
    queryKey: statusQueryKeys.summary(),
    queryFn: getStatusSummary,
    staleTime: 15_000,
    refetchInterval: 30_000,
  })
}

export function useStatusSummaryQuery() {
  return useSuspenseQuery(statusSummaryQueryOptions())
}
