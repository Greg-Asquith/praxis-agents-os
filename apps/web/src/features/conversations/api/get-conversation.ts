// apps/web/src/features/conversations/api/get-conversation.ts

import { isChatAccessLost } from "@/features/conversations/api/get-shared-chat"
import { queryOptions } from "@tanstack/react-query"

import { conversationsQueryKeys } from "@/features/conversations/api/list-conversations"
import type { ConversationDetail } from "@/features/conversations/types"
import { apiRequest } from "@/lib/api/client"

async function getConversation(
  conversationId: string,
  signal: AbortSignal
): Promise<ConversationDetail | null> {
  try {
    return await apiRequest<ConversationDetail>(
      `/conversations/${encodeURIComponent(conversationId)}`,
      { signal }
    )
  } catch (error) {
    if (isChatAccessLost(error)) return null
    throw error
  }
}

export function conversationQueryOptions(conversationId: string) {
  return queryOptions({
    queryKey: conversationsQueryKeys.detail(conversationId),
    queryFn: ({ signal }) => getConversation(conversationId, signal),
    staleTime: (query) => (query.state.data === null ? 0 : 15_000),
  })
}
