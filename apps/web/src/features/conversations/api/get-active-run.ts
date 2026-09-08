// apps/web/src/features/conversations/api/get-active-run.ts

import { queryOptions } from "@tanstack/react-query"

import { conversationReadRetry } from "@/features/conversations/conversation-heal-polling"
import { conversationsQueryKeys } from "@/features/conversations/api/list-conversations"
import type { ConversationActiveRunResponse } from "@/features/conversations/types"
import { apiRequest } from "@/lib/api/client"

export async function getActiveRun(conversationId: string, signal: AbortSignal) {
  return apiRequest<ConversationActiveRunResponse>(`/conversations/${conversationId}/active-run`, {
    signal,
  })
}

export function conversationActiveRunQueryOptions(conversationId: string) {
  return queryOptions({
    queryKey: conversationsQueryKeys.activeRun(conversationId),
    queryFn: ({ signal }) => getActiveRun(conversationId, signal),
    retry: conversationReadRetry,
    staleTime: 5_000,
  })
}
