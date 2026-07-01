// apps/web/src/features/conversations/api/get-active-run.ts

import { queryOptions, useSuspenseQuery } from "@tanstack/react-query"

import { conversationsQueryKeys } from "@/features/conversations/api/list-conversations"
import type { ConversationActiveRunResponse } from "@/features/conversations/types"
import { apiRequest } from "@/lib/api/client"

export async function getActiveRun(conversationId: string) {
  return apiRequest<ConversationActiveRunResponse>(`/conversations/${conversationId}/active-run`)
}

export function conversationActiveRunQueryOptions(conversationId: string) {
  return queryOptions({
    queryKey: conversationsQueryKeys.activeRun(conversationId),
    queryFn: () => getActiveRun(conversationId),
    staleTime: 5_000,
  })
}

export function useConversationActiveRunQuery(conversationId: string) {
  return useSuspenseQuery(conversationActiveRunQueryOptions(conversationId))
}
