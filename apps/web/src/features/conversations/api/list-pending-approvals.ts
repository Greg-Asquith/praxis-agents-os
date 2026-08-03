// apps/web/src/features/conversations/api/list-pending-approvals.ts

import { queryOptions, useSuspenseQuery } from "@tanstack/react-query"

import { conversationsQueryKeys } from "@/features/conversations/api/list-conversations"
import type { PendingApprovalsListResponse } from "@/features/conversations/types"
import { apiRequest } from "@/lib/api/client"

async function listPendingApprovals() {
  return apiRequest<PendingApprovalsListResponse>("/agent-runs/pending-approvals")
}

function pendingApprovalsQueryOptions() {
  return queryOptions({
    queryKey: conversationsQueryKeys.pendingApprovals(),
    queryFn: listPendingApprovals,
    staleTime: 15_000,
    refetchInterval: 30_000,
  })
}

export function usePendingApprovalsQuery() {
  return useSuspenseQuery(pendingApprovalsQueryOptions())
}
