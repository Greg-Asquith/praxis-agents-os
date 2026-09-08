// apps/web/src/features/conversations/api/get-approval-state.ts

import { queryOptions } from "@tanstack/react-query"

import { conversationReadRetry } from "@/features/conversations/conversation-heal-polling"
import { conversationsQueryKeys } from "@/features/conversations/api/list-conversations"
import type { AgentRunApprovalStateResponse } from "@/features/conversations/types"
import { apiRequest } from "@/lib/api/client"

export async function getAgentRunApprovalState(runId: string, signal: AbortSignal) {
  return apiRequest<AgentRunApprovalStateResponse>(`/agent-runs/${runId}/approval-state`, {
    signal,
  })
}

export function agentRunApprovalStateQueryOptions(runId: string, revision?: string | null) {
  return queryOptions({
    queryKey: [...conversationsQueryKeys.approvalState(runId), revision ?? null],
    queryFn: ({ signal }) => getAgentRunApprovalState(runId, signal),
    retry: conversationReadRetry,
    staleTime: 5_000,
  })
}
