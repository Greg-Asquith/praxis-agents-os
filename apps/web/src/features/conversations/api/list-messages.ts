// apps/web/src/features/conversations/api/list-messages.ts

import { queryOptions } from "@tanstack/react-query"

import { conversationReadRetry } from "@/features/conversations/conversation-heal-polling"
import { conversationsQueryKeys } from "@/features/conversations/api/list-conversations"
import type { ConversationMessagesResponse } from "@/features/conversations/types"
import { apiRequest } from "@/lib/api/client"

export async function listMessages(conversationId: string, signal: AbortSignal) {
  return apiRequest<ConversationMessagesResponse>(`/conversations/${conversationId}/messages`, {
    signal,
  })
}

export function conversationMessagesQueryOptions(conversationId: string) {
  return queryOptions({
    queryKey: conversationsQueryKeys.messages(conversationId),
    queryFn: ({ signal }) => listMessages(conversationId, signal),
    retry: conversationReadRetry,
    staleTime: 5_000,
  })
}
