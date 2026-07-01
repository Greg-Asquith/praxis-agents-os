// apps/web/src/features/conversations/api/get-approval-state.ts

import { queryOptions, useQuery } from "@tanstack/react-query"

import { conversationsQueryKeys } from "@/features/conversations/api/list-conversations"
import type { AgentRunApprovalStateResponse } from "@/features/conversations/types"
import { apiRequest } from "@/lib/api/client"

export async function getAgentRunApprovalState(runId: string) {
  return apiRequest<AgentRunApprovalStateResponse>(`/agent-runs/${runId}/approval-state`)
}

export function agentRunApprovalStateQueryOptions(runId: string) {
  return queryOptions({
    queryKey: conversationsQueryKeys.approvalState(runId),
    queryFn: () => getAgentRunApprovalState(runId),
    staleTime: 5_000,
  })
}

export function useAgentRunApprovalStateQuery(runId: string, enabled: boolean) {
  return useQuery({
    ...agentRunApprovalStateQueryOptions(runId),
    enabled,
  })
}
