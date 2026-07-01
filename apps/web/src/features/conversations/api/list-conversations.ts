// apps/web/src/features/conversations/api/list-conversations.ts

import { queryOptions, useSuspenseQuery } from "@tanstack/react-query"

import type { ConversationsListResponse } from "@/features/conversations/types"
import { apiRequest } from "@/lib/api/client"

type ListConversationsParams = {
  limit?: number
  offset?: number
}

export const conversationsQueryKeys = {
  all: ["conversations"] as const,
  lists: () => [...conversationsQueryKeys.all, "list"] as const,
  list: (params: ListConversationsParams = {}) =>
    [...conversationsQueryKeys.lists(), params] as const,
  messages: (conversationId: string) =>
    [...conversationsQueryKeys.all, conversationId, "messages"] as const,
  activeRun: (conversationId: string) =>
    [...conversationsQueryKeys.all, conversationId, "active-run"] as const,
}

export async function listConversations({ limit = 100, offset = 0 }: ListConversationsParams = {}) {
  return apiRequest<ConversationsListResponse>("/conversations/", {
    query: { limit, offset },
  })
}

export function conversationsQueryOptions(params: ListConversationsParams = {}) {
  return queryOptions({
    queryKey: conversationsQueryKeys.list(params),
    queryFn: () => listConversations(params),
    staleTime: 15_000,
  })
}

export function useConversationsQuery(params: ListConversationsParams = {}) {
  return useSuspenseQuery(conversationsQueryOptions(params))
}
