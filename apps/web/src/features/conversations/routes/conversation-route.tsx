// apps/web/src/features/conversations/routes/conversation-route.tsx

import { useEffect, useMemo, useRef } from "react"
import { useParams } from "@tanstack/react-router"
import { useQueryClient, useSuspenseQuery } from "@tanstack/react-query"

import { Separator } from "@/components/ui/separator"
import { ApprovalControls } from "@/features/conversations/components/approval-controls"
import { ConversationDetailHeader } from "@/features/conversations/components/conversation-detail-header"
import { ConversationComposer } from "@/features/conversations/components/conversation-composer"
import { ConversationNotFound } from "@/features/conversations/components/conversation-not-found"
import { MessageList } from "@/features/conversations/components/message-list"
import { useConversationWorkspace } from "@/features/conversations/conversation-workspace-context"
import { conversationActiveRunQueryOptions } from "@/features/conversations/api/get-active-run"
import {
  conversationsQueryKeys,
  useMarkConversationReadMutation,
} from "@/features/conversations/api/list-conversations"
import { useAgentRunApprovalStateQuery } from "@/features/conversations/api/get-approval-state"
import { conversationMessagesQueryOptions } from "@/features/conversations/api/list-messages"
import { useConversationAutoScroll } from "@/features/conversations/hooks/use-conversation-auto-scroll"
import { useConversationHealLoop } from "@/features/conversations/hooks/use-conversation-heal-loop"
import { conversationAgentLabel } from "@/features/conversations/format"
import { getConversationComposerDisabledReason } from "@/features/conversations/run-state"
import type {
  AgentRunResumeDecision,
  Conversation,
  PendingToolApproval,
} from "@/features/conversations/types"
import { useActiveWorkspace } from "@/features/workspaces/components/use-active-workspace"
import { getErrorMessage } from "@/lib/api/errors"

export function ConversationRoute() {
  const params = useParams({ strict: false })
  const conversationId = requireConversationId(params.conversationId)
  const { workspace } = useActiveWorkspace()
  const { conversations, stream } = useConversationWorkspace()
  const streamConversation =
    stream.conversation?.id === conversationId && stream.conversation.workspace_id === workspace.id
      ? stream.conversation
      : null
  const conversation =
    conversations.find((item) => item.id === conversationId) ?? streamConversation

  if (!conversation) {
    return <ConversationNotFound />
  }

  return <ConversationDetail conversation={conversation} conversationId={conversationId} />
}

function ConversationDetail({
  conversation,
  conversationId,
}: {
  conversation: Conversation
  conversationId: string
}) {
  const queryClient = useQueryClient()
  const { clearPersistedPendingMessages, pendingUserMessages, stream } = useConversationWorkspace()
  const { mutate: markConversationRead } = useMarkConversationReadMutation()
  const pendingMarkReadConversationIdRef = useRef<string | null>(null)
  const messagesQuery = useSuspenseQuery(conversationMessagesQueryOptions(conversationId))
  const activeRunQuery = useSuspenseQuery(conversationActiveRunQueryOptions(conversationId))
  const activeRun = activeRunQuery.data.active_run
  const shouldLoadApprovalState = activeRun?.status === "awaiting_approval"
  const approvalStateQuery = useAgentRunApprovalStateQuery(
    activeRun?.id ?? "",
    shouldLoadApprovalState
  )
  const streamMessages = useMemo(
    () => (stream.conversationId === conversationId ? stream.messages : []),
    [conversationId, stream.conversationId, stream.messages]
  )
  const streamToolCalls = useMemo(
    () => (stream.conversationId === conversationId ? Object.values(stream.toolCalls) : []),
    [stream.conversationId, stream.toolCalls, conversationId]
  )
  const streamApprovals = useMemo(
    () => (stream.conversationId === conversationId ? Object.values(stream.approvals) : []),
    [stream.conversationId, stream.approvals, conversationId]
  )
  const pendingApprovals = useMemo(
    () =>
      getPendingApprovals({
        activeRunId: activeRun?.id ?? null,
        recoveredApprovals: approvalStateQuery.data?.approvals ?? [],
        streamApprovals,
        streamRunId: stream.runId,
      }),
    [activeRun?.id, approvalStateQuery.data?.approvals, stream.runId, streamApprovals]
  )
  useConversationHealLoop(conversationId, activeRun)
  const scrollRef = useConversationAutoScroll({
    messageCount: messagesQuery.data.messages.length,
    pendingMessageCount: pendingUserMessages.length,
    streamMessages,
    streamToolCount: streamToolCalls.length,
  })

  useEffect(() => {
    clearPersistedPendingMessages(messagesQuery.data.messages)
  }, [clearPersistedPendingMessages, messagesQuery.data.messages])

  useEffect(() => {
    if (!conversation.unread) {
      if (pendingMarkReadConversationIdRef.current === conversationId) {
        pendingMarkReadConversationIdRef.current = null
      }
      return
    }

    if (pendingMarkReadConversationIdRef.current === conversationId) {
      return
    }

    pendingMarkReadConversationIdRef.current = conversationId
    markConversationRead(conversationId, {
      onError: () => {
        pendingMarkReadConversationIdRef.current = null
      },
    })
  }, [conversation.unread, conversationId, markConversationRead])

  const composerDisabledReason = getConversationComposerDisabledReason(activeRun)
  const streamError =
    stream.conversationId === conversationId ? (stream.error?.message ?? null) : null
  const approvalError = approvalStateQuery.error ? getErrorMessage(approvalStateQuery.error) : null
  const isResumingRun = activeRun !== null && stream.isStreaming && stream.runId === activeRun.id
  const assistantLabel = conversationAgentLabel(conversation, "Agent")

  async function handleApprovalSubmit(decisions: AgentRunResumeDecision[]) {
    if (!activeRun) {
      return
    }

    await stream.resumeRun({
      runId: activeRun.id,
      payload: { decisions },
    })
    await queryClient.invalidateQueries({
      queryKey: conversationsQueryKeys.approvalState(activeRun.id),
    })
  }

  return (
    <div className="bg-background flex h-full min-h-0 min-w-0 flex-col overflow-hidden rounded-xl border">
      <div className="shrink-0">
        <ConversationDetailHeader activeRun={activeRun} conversation={conversation} />
      </div>
      <Separator className="shrink-0" />

      <div ref={scrollRef} className="min-h-0 flex-1 overflow-y-auto p-4 pb-6">
        <MessageList
          activeRun={activeRun}
          assistantLabel={assistantLabel}
          conversationId={conversationId}
          isStreaming={stream.isStreaming && stream.conversationId === conversationId}
          messages={messagesQuery.data.messages}
          pendingUserMessages={pendingUserMessages}
          streamApprovals={streamApprovals}
          streamConversationId={stream.conversationId}
          streamError={streamError}
          streamMessages={streamMessages}
          streamToolCalls={streamToolCalls}
        />
      </div>

      <Separator className="shrink-0" />
      <footer className="flex shrink-0 flex-col gap-3 p-3">
        {activeRun?.status === "awaiting_approval" && (
          <ApprovalControls
            approvals={pendingApprovals}
            error={approvalError}
            isLoading={approvalStateQuery.isLoading}
            isSubmitting={isResumingRun}
            onSubmit={handleApprovalSubmit}
          />
        )}
        <ConversationComposer
          mode="turn"
          conversationId={conversationId}
          disabledReason={composerDisabledReason}
        />
      </footer>
    </div>
  )
}

function getPendingApprovals({
  activeRunId,
  recoveredApprovals,
  streamApprovals,
  streamRunId,
}: {
  activeRunId: string | null
  recoveredApprovals: PendingToolApproval[]
  streamApprovals: PendingToolApproval[]
  streamRunId: string | null
}) {
  if (recoveredApprovals.length > 0) {
    return recoveredApprovals
  }

  if (activeRunId !== null && streamRunId === activeRunId) {
    return streamApprovals
  }

  return []
}

function requireConversationId(value: string | undefined) {
  if (!value) {
    throw new Error("Conversation route is missing a conversation id.")
  }
  return value
}
