// apps/web/src/features/conversations/api/cancel-run.ts

import { useMutation, useQueryClient, type QueryClient } from "@tanstack/react-query"

import { conversationsQueryKeys } from "@/features/conversations/api/list-conversations"
import type { AgentRunCancelResponse } from "@/features/conversations/types"
import { apiRequest } from "@/lib/api/client"

type CancelAgentRunInput = {
  runId: string
  conversationId?: string | null
}

async function cancelAgentRun(runId: string) {
  return apiRequest<AgentRunCancelResponse>(`/agent-runs/${runId}/cancel`, {
    method: "POST",
  })
}

async function invalidateCancelledRunQueries(
  queryClient: QueryClient,
  response: AgentRunCancelResponse,
  conversationId?: string | null
) {
  const resolvedConversationId = conversationId ?? response.run.conversation_id
  await Promise.all([
    queryClient.invalidateQueries({ queryKey: conversationsQueryKeys.lists() }),
    queryClient.invalidateQueries({
      queryKey: conversationsQueryKeys.detail(resolvedConversationId),
    }),
    queryClient.invalidateQueries({
      queryKey: conversationsQueryKeys.messages(resolvedConversationId),
    }),
    queryClient.invalidateQueries({
      queryKey: conversationsQueryKeys.activeRun(resolvedConversationId),
    }),
  ])
}

export function useCancelAgentRunMutation() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: ({ runId }: CancelAgentRunInput) => cancelAgentRun(runId),
    onSuccess: async (response, input) => {
      await invalidateCancelledRunQueries(queryClient, response, input.conversationId)
    },
  })
}
