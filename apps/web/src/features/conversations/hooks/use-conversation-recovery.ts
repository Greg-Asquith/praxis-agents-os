// apps/web/src/features/conversations/hooks/use-conversation-recovery.ts

import { useMemo } from "react"
import { useQuery, useQueryClient } from "@tanstack/react-query"

import { agentRunApprovalStateQueryOptions } from "@/features/conversations/api/get-approval-state"
import { conversationRecoveryQueryOptions } from "@/features/conversations/api/get-conversation-recovery"
import { conversationMessagesQueryOptions } from "@/features/conversations/api/list-messages"
import {
  conversationActiveRunRefetchInterval,
  createConversationRecoveryCounter,
  isConversationReadRecoverable,
} from "@/features/conversations/conversation-heal-polling"
import type { ConversationActiveRunResponse } from "@/features/conversations/types"

export function useConversationRecovery(
  conversationId: string,
  streamConnected: boolean,
  initialActiveRun?: ConversationActiveRunResponse
) {
  const client = useQueryClient()
  const options = conversationRecoveryQueryOptions(client, conversationId)
  const scope = JSON.stringify(options.queryKey)
  const counter = useMemo(() => ({ count: createConversationRecoveryCounter(), scope }), [scope])
  const activeRunQuery = useQuery({
    ...options,
    refetchOnMount: "always",
    ...(initialActiveRun ? { initialData: initialActiveRun } : {}),
    refetchOnWindowFocus: (query) =>
      query.state.error === null || isConversationReadRecoverable(query.state.error),
    refetchOnReconnect: (query) =>
      query.state.error === null || isConversationReadRecoverable(query.state.error),
    refetchInterval: (query) =>
      conversationActiveRunRefetchInterval(
        query.state.data,
        query.state.error,
        streamConnected,
        Date.now(),
        counter.count(query.state)
      ),
  })
  const messagesQuery = useQuery({
    ...conversationMessagesQueryOptions(conversationId),
    enabled: false,
  })
  const active = activeRunQuery.data?.active_run
  const approvalStateQuery = useQuery({
    ...agentRunApprovalStateQueryOptions(active?.id ?? "", activeRunQuery.data?.approval_revision),
    enabled: false,
  })

  return {
    activeRunQuery,
    messagesQuery,
    approvalStateQuery,
    refresh: () => client.fetchQuery({ ...options, staleTime: 0 }),
    refreshing: activeRunQuery.isFetching,
    paused: activeRunQuery.isPaused,
    error: activeRunQuery.error,
    approvalUnavailable:
      activeRunQuery.isError ||
      activeRunQuery.isFetching ||
      activeRunQuery.isPaused ||
      !approvalStateQuery.data,
  }
}
