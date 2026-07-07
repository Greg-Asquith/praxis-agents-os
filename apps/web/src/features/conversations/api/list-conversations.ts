// apps/web/src/features/conversations/api/list-conversations.ts

import {
  queryOptions,
  useMutation,
  useQueryClient,
  useSuspenseQuery,
  type QueryClient,
} from "@tanstack/react-query"

import type { Conversation, ConversationsListResponse } from "@/features/conversations/types"
import { createWorkspaceScopedQueryKeys } from "@/features/workspaces/query-keys"
import { apiRequest } from "@/lib/api/client"

type ListConversationsParams = {
  limit?: number
  offset?: number
}

const baseConversationsQueryKeys = createWorkspaceScopedQueryKeys("conversations")

export const conversationsQueryKeys = {
  all: baseConversationsQueryKeys.all,
  workspace: baseConversationsQueryKeys.workspace,
  lists: baseConversationsQueryKeys.lists,
  list: (params: ListConversationsParams = {}) => baseConversationsQueryKeys.list(params),
  detail: (conversationId: string) =>
    [...conversationsQueryKeys.workspace(), conversationId, "detail"] as const,
  messages: (conversationId: string) =>
    [...conversationsQueryKeys.workspace(), conversationId, "messages"] as const,
  activeRun: (conversationId: string) =>
    [...conversationsQueryKeys.workspace(), conversationId, "active-run"] as const,
  approvalState: (runId: string) =>
    [...conversationsQueryKeys.workspace(), "agent-run", runId, "approval-state"] as const,
}

async function listConversations({ limit = 100, offset = 0 }: ListConversationsParams = {}) {
  return apiRequest<ConversationsListResponse>("/conversations/", {
    query: { limit, offset },
  })
}

async function markConversationRead(conversationId: string) {
  return apiRequest<Conversation>(`/conversations/${conversationId}/read`, {
    method: "POST",
  })
}

async function invalidateConversationQueries(queryClient: QueryClient, conversationId?: string) {
  const invalidations = [
    queryClient.invalidateQueries({ queryKey: conversationsQueryKeys.lists() }),
  ]

  if (conversationId) {
    invalidations.push(
      queryClient.invalidateQueries({
        queryKey: conversationsQueryKeys.detail(conversationId),
      }),
      queryClient.invalidateQueries({
        queryKey: conversationsQueryKeys.messages(conversationId),
      }),
      queryClient.invalidateQueries({
        queryKey: conversationsQueryKeys.activeRun(conversationId),
      })
    )
  }

  await Promise.all(invalidations)
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

export function useMarkConversationReadMutation() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: markConversationRead,
    onSuccess: async (_conversation, conversationId) => {
      await invalidateConversationQueries(queryClient, conversationId)
    },
  })
}
