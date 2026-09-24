// apps/web/src/features/conversations/api/list-conversations.ts

import {
  queryOptions,
  useMutation,
  useQueryClient,
  useSuspenseQuery,
  type QueryClient,
} from "@tanstack/react-query"

import type {
  Conversation,
  ConversationDetail,
  ConversationsListResponse,
} from "@/features/conversations/types"
import { createWorkspaceScopedQueryKeys } from "@/lib/workspace"
import { apiRequest } from "@/lib/api/client"

type ConversationScope = "mine" | "all"
type ListConversationsParams<Scope extends ConversationScope = ConversationScope> = {
  limit?: number
  offset?: number
  scope?: Scope
}

const baseConversationsQueryKeys = createWorkspaceScopedQueryKeys("conversations")

export const conversationsQueryKeys = {
  all: baseConversationsQueryKeys.all,
  workspace: baseConversationsQueryKeys.workspace,
  lists: baseConversationsQueryKeys.lists,
  list: (params: ListConversationsParams = {}) =>
    baseConversationsQueryKeys.list({ ...params, scope: params.scope ?? "mine" }),
  detail: (conversationId: string) =>
    [...conversationsQueryKeys.workspace(), conversationId, "detail"] as const,
  messages: (conversationId: string) =>
    [...conversationsQueryKeys.workspace(), conversationId, "messages"] as const,
  activeRun: (conversationId: string) =>
    [...conversationsQueryKeys.workspace(), conversationId, "active-run"] as const,
  approvalState: (runId: string) =>
    [...conversationsQueryKeys.workspace(), "agent-run", runId, "approval-state"] as const,
  pendingApprovals: () =>
    [...conversationsQueryKeys.workspace(), "agent-runs", "pending-approvals"] as const,
}

async function listConversations<Scope extends ConversationScope>(
  params: ListConversationsParams<Scope>
) {
  const { limit = 100, offset = 0, scope = "mine" } = params
  return apiRequest<
    ConversationsListResponse<Scope extends "mine" ? Conversation : ConversationDetail>
  >("/conversations/", {
    query: { limit, offset, scope },
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

export function conversationsQueryOptions<Scope extends ConversationScope = "mine">(
  params: ListConversationsParams<Scope> = {}
) {
  return queryOptions({
    queryKey: conversationsQueryKeys.list(params),
    queryFn: () => listConversations(params),
    staleTime: 15_000,
  })
}

export function useConversationsQuery<Scope extends ConversationScope = "mine">(
  params: ListConversationsParams<Scope> = {}
) {
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
