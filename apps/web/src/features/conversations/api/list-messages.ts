// apps/web/src/features/conversations/api/list-messages.ts

import { queryOptions } from "@tanstack/react-query"

import { conversationsQueryKeys } from "@/features/conversations/api/list-conversations"
import type { ConversationMessagesResponse } from "@/features/conversations/types"
import { apiRequest } from "@/lib/api/client"

async function listMessages(conversationId: string) {
  return apiRequest<ConversationMessagesResponse>(`/conversations/${conversationId}/messages`)
}

export function conversationMessagesQueryOptions(conversationId: string) {
  return queryOptions({
    queryKey: conversationsQueryKeys.messages(conversationId),
    queryFn: () => listMessages(conversationId),
    staleTime: 5_000,
  })
}
