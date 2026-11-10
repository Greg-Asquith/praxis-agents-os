// apps/web/src/features/conversations/hooks/use-conversation-recovery.ts

import { useMemo, useState } from "react"
import { useQuery, useQueryClient } from "@tanstack/react-query"

import { agentRunApprovalStateQueryOptions } from "@/features/conversations/api/get-approval-state"
import { conversationRecoveryQueryOptions } from "@/features/conversations/api/get-conversation-recovery"
import { conversationMessagesQueryOptions } from "@/features/conversations/api/list-messages"
import {
  conversationActiveRunRefetchInterval,
  createConversationRecoveryCounter,
  isConversationReadRecoverable,
} from "@/features/conversations/conversation-heal-polling"
import type {
  ConversationActiveRunResponse,
  PendingWorkflowState,
} from "@/features/conversations/types"

const NO_WORKFLOWS: PendingWorkflowState[] = []

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

  // A resumed run has no approval state, so its script keeps the last one fetched.
  const [retained, setRetained] = useState<{ runId: string; workflows: PendingWorkflowState[] }>()
  const workflows = approvalStateQuery.data?.workflows
  if (active && workflows && retained?.workflows !== workflows) {
    setRetained({ runId: active.id, workflows })
  }
  const pendingWorkflows =
    workflows ?? (active && retained?.runId === active.id ? retained.workflows : NO_WORKFLOWS)

  return {
    pendingWorkflows,
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
