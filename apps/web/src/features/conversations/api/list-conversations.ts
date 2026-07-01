// apps/web/src/features/conversations/api/list-conversations.ts

import {
  queryOptions,
  useMutation,
  useQueryClient,
  useSuspenseQuery,
  type QueryClient,
} from "@tanstack/react-query"

import type { Conversation, ConversationsListResponse } from "@/features/conversations/types"
import { apiRequest } from "@/lib/api/client"
import { getActiveWorkspaceSlug } from "@/features/workspaces/workspace-context"

type ListConversationsParams = {
  limit?: number
  offset?: number
}

export const conversationsQueryKeys = {
  all: ["conversations"] as const,
  workspace: () => [...conversationsQueryKeys.all, activeWorkspaceQueryScope()] as const,
  lists: () => [...conversationsQueryKeys.workspace(), "list"] as const,
  list: (params: ListConversationsParams = {}) =>
    [...conversationsQueryKeys.lists(), params] as const,
  messages: (conversationId: string) =>
    [...conversationsQueryKeys.workspace(), conversationId, "messages"] as const,
  activeRun: (conversationId: string) =>
    [...conversationsQueryKeys.workspace(), conversationId, "active-run"] as const,
  approvalState: (runId: string) =>
    [...conversationsQueryKeys.workspace(), "agent-run", runId, "approval-state"] as const,
}

function activeWorkspaceQueryScope() {
  return getActiveWorkspaceSlug() ?? "__no_workspace__"
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
