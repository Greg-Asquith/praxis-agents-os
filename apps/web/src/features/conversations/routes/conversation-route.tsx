// apps/web/src/features/conversations/routes/conversation-route.tsx

import { useEffect, useMemo, useRef, useState } from "react"
import { useParams } from "@tanstack/react-router"
import { useQueryClient, useSuspenseQuery } from "@tanstack/react-query"

import { Separator } from "@/components/ui/separator"
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
  const [submittingApprovalRunId, setSubmittingApprovalRunId] = useState<string | null>(null)
  const messagesQuery = useSuspenseQuery(conversationMessagesQueryOptions(conversationId))
  const activeRunQuery = useSuspenseQuery(conversationActiveRunQueryOptions(conversationId))
  const activeRun = activeRunQuery.data.active_run
  const activeRunId = activeRun?.id ?? null
  const activeRunStatus = activeRun?.status ?? null
  const shouldLoadApprovalState = activeRunStatus === "awaiting_approval"
  const approvalStateQuery = useAgentRunApprovalStateQuery(
    activeRunId ?? "",
    shouldLoadApprovalState
  )
  const hasPersistedStreamRun = useMemo(
    () =>
      stream.runId !== null &&
      messagesQuery.data.messages.some(
        (message) => message.metadata?.["agent_run_id"] === stream.runId
      ),
    [messagesQuery.data.messages, stream.runId]
  )
  const shouldRenderStream = shouldRenderConversationStream({
    activeRun,
    conversationId,
    hasPersistedStreamRun,
    streamConversationId: stream.conversationId,
    submittingApprovalRunId,
  })
  const streamMessages = useMemo(
    () => (shouldRenderStream ? stream.messages : []),
    [shouldRenderStream, stream.messages]
  )
  const streamToolCalls = useMemo(
    () => (shouldRenderStream ? Object.values(stream.toolCalls) : []),
    [shouldRenderStream, stream.toolCalls]
  )
  const streamApprovals = useMemo(
    () => (stream.conversationId === conversationId ? Object.values(stream.approvals) : []),
    [stream.conversationId, stream.approvals, conversationId]
  )
  const visibleStreamApprovals = useMemo(
    () => (shouldRenderStream ? streamApprovals : []),
    [shouldRenderStream, streamApprovals]
  )
  const pendingApprovals = useMemo(
    () =>
      getPendingApprovals({
        activeRunId,
        recoveredApprovals: approvalStateQuery.data?.approvals ?? [],
        streamApprovals,
        streamRunId: stream.runId,
      }),
    [activeRunId, approvalStateQuery.data?.approvals, stream.runId, streamApprovals]
  )
  useConversationHealLoop(conversationId, activeRun)
  const scrollRef = useConversationAutoScroll({
    approvalCount: pendingApprovals.length,
    messageCount: messagesQuery.data.messages.length,
    pendingMessageCount: pendingUserMessages.length,
    streamMessages,
    streamToolCount: streamToolCalls.length,
  })

  useEffect(() => {
    clearPersistedPendingMessages(messagesQuery.data.messages)
  }, [clearPersistedPendingMessages, messagesQuery.data.messages])

  useEffect(() => {
    if (stream.conversationId !== conversationId) {
      return
    }

    const streamMatchesPendingApproval =
      activeRunStatus === "awaiting_approval" &&
      activeRunId !== null &&
      submittingApprovalRunId !== activeRunId &&
      stream.runId === activeRunId
    const streamMatchesPersistedSettledRun = activeRunId === null && hasPersistedStreamRun

    if (!streamMatchesPendingApproval && !streamMatchesPersistedSettledRun) {
      return
    }

    if (
      stream.isStreaming ||
      stream.messages.length > 0 ||
      Object.keys(stream.toolCalls).length > 0 ||
      Object.keys(stream.approvals).length > 0
    ) {
      stream.reset()
    }
  }, [
    activeRunId,
    activeRunStatus,
    conversationId,
    hasPersistedStreamRun,
    stream,
    stream.conversationId,
    stream.isStreaming,
    stream.messages.length,
    stream.runId,
    stream.toolCalls,
    stream.approvals,
    submittingApprovalRunId,
  ])

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
    shouldRenderStream && stream.conversationId === conversationId
      ? (stream.error?.message ?? null)
      : null
  const approvalError = approvalStateQuery.error ? getErrorMessage(approvalStateQuery.error) : null
  const isResumingRun = activeRunId !== null && submittingApprovalRunId === activeRunId
  const assistantLabel = conversationAgentLabel(conversation, "Agent")

  async function handleApprovalSubmit(decisions: AgentRunResumeDecision[]) {
    if (!activeRun) {
      return
    }

    const runId = activeRun.id
    setSubmittingApprovalRunId(runId)
    try {
      await stream.resumeRun({
        runId,
        payload: { decisions },
      })
      await queryClient.invalidateQueries({
        queryKey: conversationsQueryKeys.approvalState(runId),
      })
    } finally {
      setSubmittingApprovalRunId((currentRunId) => (currentRunId === runId ? null : currentRunId))
    }
  }

  return (
    <div className="bg-background flex h-full min-h-0 min-w-0 flex-col overflow-hidden">
      <div className="shrink-0">
        <ConversationDetailHeader activeRun={activeRun} conversation={conversation} />
      </div>
      <Separator className="shrink-0" />

      <div ref={scrollRef} className="min-h-0 flex-1 overflow-y-auto">
        <div className="mx-auto w-full max-w-5xl px-4 py-4 pb-6">
          <MessageList
            activeRun={activeRun}
            approvalError={approvalError}
            approvals={pendingApprovals}
            assistantLabel={assistantLabel}
            conversationId={conversationId}
            isApprovalLoading={approvalStateQuery.isLoading}
            isApprovalSubmitting={isResumingRun}
            isStreaming={shouldRenderStream && stream.isStreaming}
            messages={messagesQuery.data.messages}
            onApprovalSubmit={handleApprovalSubmit}
            pendingUserMessages={pendingUserMessages}
            streamApprovals={visibleStreamApprovals}
            streamConversationId={shouldRenderStream ? stream.conversationId : null}
            streamError={streamError}
            streamMessages={streamMessages}
            streamToolCalls={streamToolCalls}
          />
        </div>
      </div>

      <Separator className="shrink-0" />
      <footer className="max-h-[45%] shrink-0 overflow-y-auto">
        <div className="mx-auto flex w-full max-w-5xl flex-col gap-3 px-4 py-3">
          <ConversationComposer
            mode="turn"
            conversationId={conversationId}
            disabledReason={composerDisabledReason}
          />
        </div>
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

function shouldRenderConversationStream({
  activeRun,
  conversationId,
  hasPersistedStreamRun,
  streamConversationId,
  submittingApprovalRunId,
}: {
  activeRun: { id: string; status: string } | null
  conversationId: string
  hasPersistedStreamRun: boolean
  streamConversationId: string | null
  submittingApprovalRunId: string | null
}) {
  if (streamConversationId !== conversationId) {
    return false
  }

  if (activeRun === null && hasPersistedStreamRun) {
    return false
  }

  return activeRun?.status !== "awaiting_approval" || submittingApprovalRunId === activeRun.id
}

function requireConversationId(value: string | undefined) {
  if (!value) {
    throw new Error("Conversation route is missing a conversation id.")
  }
  return value
}
