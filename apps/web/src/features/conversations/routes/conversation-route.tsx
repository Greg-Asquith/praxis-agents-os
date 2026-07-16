// apps/web/src/features/conversations/routes/conversation-route.tsx

import { useEffect, useState } from "react"
import { useParams } from "@tanstack/react-router"
import { useQueryClient, useSuspenseQueries, useSuspenseQuery } from "@tanstack/react-query"
import { ArrowDownIcon, LockKeyholeIcon } from "lucide-react"

import { Button } from "@/components/ui/button"
import { Separator } from "@/components/ui/separator"
import { agentQueryOptions } from "@/features/agents/api/get-agent"
import { ConversationDetailHeader } from "@/features/conversations/components/conversation-detail-header"
import { ConversationComposer } from "@/features/conversations/components/conversation-composer"
import { MessageList } from "@/features/conversations/components/message-list"
import { useConversationWorkspace } from "@/features/conversations/conversation-workspace-context"
import { conversationQueryOptions } from "@/features/conversations/api/get-conversation"
import { conversationActiveRunQueryOptions } from "@/features/conversations/api/get-active-run"
import { conversationsQueryKeys } from "@/features/conversations/api/list-conversations"
import { useAgentRunApprovalStateQuery } from "@/features/conversations/api/get-approval-state"
import { conversationMessagesQueryOptions } from "@/features/conversations/api/list-messages"
import { useConversationAutoScroll } from "@/features/conversations/hooks/use-conversation-auto-scroll"
import { useConversationHealLoop } from "@/features/conversations/hooks/use-conversation-heal-loop"
import { useConversationReadReceipt } from "@/features/conversations/hooks/use-conversation-read-receipt"
import { useConversationRunState } from "@/features/conversations/hooks/use-conversation-run-state"
import { conversationAgentLabel } from "@/features/conversations/format"
import { getConversationComposerDisabledReason } from "@/features/conversations/run-state"
import {
  EMPTY_CONVERSATION_MESSAGES,
  streamActiveRunFromState,
} from "@/features/conversations/stream/query-cache"
import type {
  AgentRunResumeDecision,
  Conversation,
  ConversationActiveRunResponse,
} from "@/features/conversations/types"
import { modelCatalogQueryOptions } from "@/features/models/api/list-model-catalog"
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
  const listedConversation = conversations.find((item) => item.id === conversationId)
  const initialConversation = streamConversation ?? listedConversation
  const conversationQuery = useSuspenseQuery({
    ...conversationQueryOptions(conversationId),
    ...(initialConversation ? { initialData: initialConversation } : {}),
  })
  const conversation = streamConversation ?? listedConversation ?? conversationQuery.data

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
  const [submittingApprovalRunId, setSubmittingApprovalRunId] = useState<string | null>(null)
  const isLiveStreamConversation = stream.conversationId === conversationId
  const streamActiveRun = streamActiveRunFromState({
    conversation,
    done: stream.done,
    runId: stream.runId,
    status: stream.status,
  })
  const initialActiveRun =
    isLiveStreamConversation && streamActiveRun !== undefined
      ? ({ active_run: streamActiveRun } satisfies ConversationActiveRunResponse)
      : undefined
  const messagesQuery = useSuspenseQuery({
    ...conversationMessagesQueryOptions(conversationId),
    ...(isLiveStreamConversation ? { initialData: EMPTY_CONVERSATION_MESSAGES } : {}),
  })
  const activeRunQuery = useSuspenseQuery({
    ...conversationActiveRunQueryOptions(conversationId),
    ...(initialActiveRun ? { initialData: initialActiveRun } : {}),
  })
  const [agentQuery, modelCatalogQuery] = useSuspenseQueries({
    queries: [agentQueryOptions(conversation.active_agent_id ?? ""), modelCatalogQueryOptions()],
  })
  const activeRun = streamActiveRun ?? activeRunQuery.data.active_run
  const activeRunId = activeRun?.id ?? null
  const activeRunStatus = activeRun?.status ?? null
  const shouldLoadApprovalState = activeRunStatus === "awaiting_approval"
  const approvalStateQuery = useAgentRunApprovalStateQuery(
    activeRunId ?? "",
    shouldLoadApprovalState
  )
  const {
    pendingApprovals,
    pendingDelegations,
    shouldRenderStream,
    streamError,
    streamMessages,
    streamToolCalls,
    visibleStreamApprovals,
  } = useConversationRunState({
    activeRun,
    conversationId,
    messages: messagesQuery.data.messages,
    recoveredApprovals: approvalStateQuery.data?.approvals ?? [],
    recoveredDelegations: approvalStateQuery.data?.delegations ?? [],
    stream,
    submittingApprovalRunId,
  })
  useConversationHealLoop(conversationId, activeRun)
  const { handleScroll, isAwayFromBottom, scrollRef, scrollToBottom } = useConversationAutoScroll({
    approvalCount: pendingApprovals.length,
    messageCount: messagesQuery.data.messages.length,
    pendingMessageCount: pendingUserMessages.length,
    streamMessages,
    streamToolCount: streamToolCalls.length,
  })

  useEffect(() => {
    clearPersistedPendingMessages(messagesQuery.data.messages)
  }, [clearPersistedPendingMessages, messagesQuery.data.messages])
  useConversationReadReceipt({
    conversationId,
    unread: conversation.unread,
  })

  const composerDisabledReason = getConversationComposerDisabledReason(activeRun)
  const approvalError = approvalStateQuery.error ? getErrorMessage(approvalStateQuery.error) : null
  const isResumingRun = activeRunId !== null && submittingApprovalRunId === activeRunId
  const assistantLabel = conversationAgentLabel(conversation, "Agent")
  const assistantAgentId = activeRun?.agent_id ?? conversation.active_agent_id ?? "unassigned-agent"
  const isReadOnlyTranscript = conversation.source === "delegated"
  const showScrollToBottom = shouldRenderStream && stream.isStreaming && isAwayFromBottom

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

      <div className="relative min-h-0 flex-1">
        <div ref={scrollRef} className="h-full overflow-y-auto" onScroll={handleScroll}>
          <div className="mx-auto w-full max-w-4xl px-6 py-6 pb-8">
            <MessageList
              activeRun={activeRun}
              approvalError={approvalError}
              approvals={pendingApprovals}
              assistantAgentId={assistantAgentId}
              assistantLabel={assistantLabel}
              conversationId={conversationId}
              isApprovalLoading={approvalStateQuery.isLoading}
              isApprovalSubmitting={isResumingRun}
              isStreaming={shouldRenderStream && stream.isStreaming}
              messages={messagesQuery.data.messages}
              onApprovalSubmit={handleApprovalSubmit}
              pendingDelegations={pendingDelegations}
              pendingUserMessages={pendingUserMessages}
              streamApprovals={visibleStreamApprovals}
              streamConversationId={shouldRenderStream ? stream.conversationId : null}
              streamError={streamError}
              streamMessages={streamMessages}
              streamToolCalls={streamToolCalls}
            />
          </div>
        </div>
        {showScrollToBottom ? (
          <Button
            aria-label="Scroll to Latest Message"
            className="absolute bottom-3 left-1/2 -translate-x-1/2 rounded-full shadow-sm"
            size="icon"
            type="button"
            variant="outline"
            onClick={scrollToBottom}
          >
            <ArrowDownIcon className="size-4" />
          </Button>
        ) : null}
      </div>

      {isReadOnlyTranscript ? (
        <footer className="shrink-0">
          <Separator />
          <div className="mx-auto flex w-full max-w-4xl items-center gap-2 px-6 py-3 text-sm">
            <LockKeyholeIcon className="text-muted-foreground size-4 shrink-0" />
            <span className="text-muted-foreground">Read-only delegated transcript</span>
          </div>
        </footer>
      ) : (
        <footer className="max-h-[45%] shrink-0 overflow-y-auto">
          <div className="mx-auto flex w-full max-w-4xl flex-col gap-3 px-6 pt-2 pb-4">
            <ConversationComposer
              agent={agentQuery.data}
              mode="turn"
              modelCatalog={modelCatalogQuery.data}
              conversationId={conversationId}
              disabledReason={composerDisabledReason}
            />
          </div>
        </footer>
      )}
    </div>
  )
}

function requireConversationId(value: string | undefined) {
  if (!value) {
    throw new Error("Conversation route is missing a conversation id.")
  }
  return value
}
