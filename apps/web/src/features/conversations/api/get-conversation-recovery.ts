// apps/web/src/features/conversations/api/get-conversation-recovery.ts

import { CancelledError, queryOptions, type QueryClient } from "@tanstack/react-query"

import {
  conversationActiveRunQueryOptions,
  getActiveRun,
} from "@/features/conversations/api/get-active-run"
import {
  agentRunApprovalStateQueryOptions,
  getAgentRunApprovalState,
} from "@/features/conversations/api/get-approval-state"
import {
  conversationMessagesQueryOptions,
  listMessages,
} from "@/features/conversations/api/list-messages"
import { ConversationProjectionChangedError } from "@/features/conversations/conversation-heal-polling"
import { activeUserQueryScope, activeWorkspaceQueryScope } from "@/lib/workspace"

export function conversationRecoveryQueryOptions(client: QueryClient, conversationId: string) {
  const activeOptions = conversationActiveRunQueryOptions(conversationId)
  const messagesOptions = conversationMessagesQueryOptions(conversationId)
  const workspace = activeWorkspaceQueryScope()
  const user = activeUserQueryScope()

  function assertCurrentScope(signal: AbortSignal) {
    signal.throwIfAborted()
    if (workspace !== activeWorkspaceQueryScope() || user !== activeUserQueryScope()) {
      throw new CancelledError()
    }
  }

  return queryOptions({
    ...activeOptions,
    queryFn: async (context) => {
      assertCurrentScope(context.signal)
      const response = await getActiveRun(conversationId, context.signal)
      assertCurrentScope(context.signal)
      const approvalRunId =
        response.active_run?.status === "awaiting_approval" ? response.active_run.id : null
      // Publish a recovered status only with its corresponding transcript and proposal.
      const [, approval] = await Promise.all([
        client.fetchQuery({
          ...messagesOptions,
          staleTime: 0,
          retry: false,
          queryFn: ({ signal }) =>
            listMessages(conversationId, AbortSignal.any([context.signal, signal])),
        }),
        approvalRunId !== null
          ? client.fetchQuery({
              ...agentRunApprovalStateQueryOptions(approvalRunId, response.approval_revision),
              staleTime: 0,
              retry: false,
              queryFn: ({ signal }) =>
                getAgentRunApprovalState(approvalRunId, AbortSignal.any([context.signal, signal])),
            })
          : Promise.resolve(),
      ])
      assertCurrentScope(context.signal)
      if (
        approval &&
        (approval.run_id !== approvalRunId ||
          approval.approval_revision !== response.approval_revision)
      ) {
        throw new ConversationProjectionChangedError()
      }
      return response
    },
  })
}
