// apps/web/src/features/conversations/api/get-conversation.ts

import { queryOptions } from "@tanstack/react-query"

import { conversationsQueryKeys } from "@/features/conversations/api/list-conversations"
import type { Conversation } from "@/features/conversations/types"
import { apiRequest } from "@/lib/api/client"

async function getConversation(conversationId: string) {
  return apiRequest<Conversation>(`/conversations/${conversationId}`)
}

export function conversationQueryOptions(conversationId: string) {
  return queryOptions({
    queryKey: conversationsQueryKeys.detail(conversationId),
    queryFn: () => getConversation(conversationId),
    staleTime: 15_000,
  })
}
