// apps/web/src/features/conversations/api/list-messages.ts

import { queryOptions, useSuspenseQuery } from "@tanstack/react-query"

import { conversationsQueryKeys } from "@/features/conversations/api/list-conversations"
import type { ConversationMessagesResponse } from "@/features/conversations/types"
import { apiRequest } from "@/lib/api/client"

export async function listMessages(conversationId: string) {
  return apiRequest<ConversationMessagesResponse>(
    `/conversations/${conversationId}/messages`
  )
}

export function conversationMessagesQueryOptions(conversationId: string) {
  return queryOptions({
    queryKey: conversationsQueryKeys.messages(conversationId),
    queryFn: () => listMessages(conversationId),
    staleTime: 5_000,
  })
}

export function useConversationMessagesQuery(conversationId: string) {
  return useSuspenseQuery(conversationMessagesQueryOptions(conversationId))
}
