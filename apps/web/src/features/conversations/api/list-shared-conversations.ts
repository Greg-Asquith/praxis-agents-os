// apps/web/src/features/conversations/api/list-shared-conversations.ts

import { queryOptions, useSuspenseQuery } from "@tanstack/react-query"

import { conversationsQueryKeys } from "@/features/conversations/api/list-conversations"
import type { SharedConversation } from "@/features/conversations/types"
import { apiRequest } from "@/lib/api/client"

export function sharedConversationsQueryOptions({ limit = 100, offset = 0 } = {}) {
  return queryOptions({
    queryKey: [...conversationsQueryKeys.lists(), { scope: "workspace_shared", limit, offset }],
    queryFn: ({ signal }) =>
      apiRequest<{
        conversations: SharedConversation[]
        total: number
        limit: number
        offset: number
      }>("/conversations/", { signal, query: { scope: "workspace_shared", limit, offset } }),
    staleTime: 0,
  })
}

export function useSharedConversationsQuery(params: { limit?: number; offset?: number } = {}) {
  return useSuspenseQuery(sharedConversationsQueryOptions(params))
}
