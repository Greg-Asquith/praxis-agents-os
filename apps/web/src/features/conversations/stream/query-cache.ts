// apps/web/src/features/conversations/stream/query-cache.ts

import type { QueryClient } from "@tanstack/react-query"

import { conversationsQueryKeys } from "@/features/conversations/api/list-conversations"
import type {
  AgentRun,
  AgentRunStatus,
  Conversation,
  ConversationActiveRunResponse,
  ConversationMessagesResponse,
} from "@/features/conversations/types"
import type { StreamEvent } from "@/features/conversations/stream/protocol"

export const EMPTY_CONVERSATION_MESSAGES = {
  messages: [],
  total: 0,
} satisfies ConversationMessagesResponse

export function seedStreamQueryCache(queryClient: QueryClient, streamEvent: StreamEvent) {
  if (streamEvent.event === "conversation.created") {
    const conversation = streamEvent.data.conversation
    queryClient.setQueryData(conversationsQueryKeys.detail(conversation.id), conversation)
    queryClient.setQueryData<ConversationMessagesResponse>(
      conversationsQueryKeys.messages(conversation.id),
      (current) => current ?? EMPTY_CONVERSATION_MESSAGES
    )
    queryClient.setQueryData<ConversationActiveRunResponse>(
      conversationsQueryKeys.activeRun(conversation.id),
      (current) =>
        current ?? {
          active_run: buildStreamAgentRun(
            conversation,
            streamEvent.data.run_id,
            conversation.active_run_status ?? "pending"
          ),
        }
    )
    return
  }

  if (streamEvent.event === "conversation.updated") {
    queryClient.setQueryData(
      conversationsQueryKeys.detail(streamEvent.data.conversation.id),
      streamEvent.data.conversation
    )
    return
  }

  if (streamEvent.event !== "run.status") {
    return
  }

  const conversationId = streamEvent.data.conversation_id
  const status = streamEvent.data.status
  queryClient.setQueryData<Conversation>(
    conversationsQueryKeys.detail(conversationId),
    (current) =>
      current
        ? {
            ...current,
            active_run_id: isActiveRunStatus(status) ? streamEvent.data.run_id : null,
            active_run_status: isActiveRunStatus(status) ? status : null,
            needs_approval: status === "awaiting_approval",
          }
        : current
  )
  queryClient.setQueryData<ConversationActiveRunResponse>(
    conversationsQueryKeys.activeRun(conversationId),
    (current) => {
      if (!isActiveRunStatus(status)) {
        return { active_run: null }
      }

      if (current?.active_run) {
        return {
          active_run: {
            ...current.active_run,
            status,
          },
        }
      }

      const conversation = queryClient.getQueryData<Conversation>(
        conversationsQueryKeys.detail(conversationId)
      )
      return {
        active_run: conversation
          ? buildStreamAgentRun(conversation, streamEvent.data.run_id, status)
          : null,
      }
    }
  )
}

export function streamActiveRunFromState({
  conversation,
  done,
  runId,
  status,
}: {
  conversation: Conversation
  done: boolean
  runId: string | null
  status: AgentRunStatus | "idle"
}): AgentRun | null | undefined {
  if (runId === null || done || !isActiveRunStatus(status)) {
    return undefined
  }

  return buildStreamAgentRun(conversation, runId, status)
}

function buildStreamAgentRun(
  conversation: Conversation,
  runId: string,
  status: AgentRunStatus
): AgentRun | null {
  if (!isActiveRunStatus(status) || conversation.active_agent_id === null) {
    return null
  }

  return {
    id: runId,
    conversation_id: conversation.id,
    agent_id: conversation.active_agent_id,
    workspace_id: conversation.workspace_id,
    user_id: conversation.user_id,
    parent_run_id: null,
    delegation_depth: 0,
    trigger: conversation.source === "scheduled" ? "scheduled" : "interactive",
    status,
    model_name: null,
    started_at: null,
    completed_at: null,
    failed_at: null,
    lease_expires_at: null,
    error_code: null,
    error_message: null,
    created_at: conversation.created_at,
    updated_at: conversation.updated_at,
  }
}

function isActiveRunStatus(status: AgentRunStatus | "idle"): status is AgentRunStatus {
  return status === "pending" || status === "running" || status === "awaiting_approval"
}
