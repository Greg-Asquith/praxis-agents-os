// apps/web/src/features/conversations/api/get-shared-chat.ts

import { infiniteQueryOptions, type QueryClient, type QueryKey } from "@tanstack/react-query"

import { conversationsQueryKeys } from "@/features/conversations/api/list-conversations"
import type { ConversationMessagesResponse } from "@/features/conversations/types"
import { apiRequest } from "@/lib/api/client"
import { ApiError } from "@/lib/api/errors"

export function isChatAccessLost(error: unknown) {
  return error instanceof ApiError && [401, 403, 404].includes(error.status)
}

export function sharedChatQueryOptions(conversationId: string) {
  return infiniteQueryOptions({
    queryKey: [...conversationsQueryKeys.messages(conversationId), "shared"],
    initialPageParam: undefined as number | undefined,
    queryFn: async ({ signal, pageParam }) => {
      try {
        return await apiRequest<ConversationMessagesResponse>(
          `/conversations/${encodeURIComponent(conversationId)}/messages`,
          { signal, query: { before_sequence: pageParam } }
        )
      } catch (error) {
        if (isChatAccessLost(error)) return null
        throw error
      }
    },
    getNextPageParam: (page) => (page?.has_more ? page.messages[0]?.sequence : undefined),
    retry: false,
    staleTime: 0,
    gcTime: 0,
  })
}

export async function clearSharedChat(
  client: QueryClient,
  keys: { detail: QueryKey; messages: QueryKey; shared: QueryKey }
) {
  await Promise.all(
    [keys.detail, keys.messages].map((queryKey) => client.cancelQueries({ queryKey }))
  )
  client.removeQueries({
    queryKey: keys.messages,
    predicate: (query) => query.queryKey.at(-1) !== "shared",
  })
  // Terminal values preserve observed queries without retaining saved content.
  client.setQueryData(keys.detail, null)
  client.setQueryData(keys.shared, { pages: [null], pageParams: [undefined] })
}
