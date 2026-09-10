// apps/web/src/features/conversations/routes/conversation-route.tsx

import { useMemo, useState } from "react"
import { Link, useParams } from "@tanstack/react-router"
import { useQuery, useSuspenseQueries, useSuspenseQuery } from "@tanstack/react-query"
import { ArrowDownIcon, LockKeyholeIcon } from "lucide-react"

import { Alert, AlertAction, AlertDescription } from "@/components/ui/alert"
import { Button } from "@/components/ui/button"
import { Separator } from "@/components/ui/separator"
import { agentQueryOptions } from "@/features/agents/api/get-agent"
import { reconcileApprovalSubmission } from "@/features/conversations/approval-submission"
import { approvalBatchIsReady } from "@/features/conversations/approval-decisions"
import { ConversationDetailHeader } from "@/features/conversations/components/conversation-detail-header"
import { ConversationComposer } from "@/features/conversations/components/conversation-composer"
import { MessageList } from "@/features/conversations/components/message-list"
import { conversationRecoveryMessage } from "@/features/conversations/conversation-heal-polling"
import { useConversationRecovery } from "@/features/conversations/hooks/use-conversation-recovery"
import { useConversationWorkspace } from "@/features/conversations/conversation-workspace-context"
import { conversationQueryOptions } from "@/features/conversations/api/get-conversation"
import { useConversationAutoScroll } from "@/features/conversations/hooks/use-conversation-auto-scroll"
import { useConversationReadReceipt } from "@/features/conversations/hooks/use-conversation-read-receipt"
import { useConversationRunState } from "@/features/conversations/hooks/use-conversation-run-state"
import {
  conversationAgentLabel,
  conversationScheduleContext,
} from "@/features/conversations/format"
import { projectConversationTimeline } from "@/features/conversations/message-parts/timeline"
import {
  getConversationComposerDisabledReason,
  resolveConversationActiveRun,
} from "@/features/conversations/run-state"
import { conversationRunInterruptionOutcome } from "@/features/conversations/run-error-copy"
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
import { scheduleQueryOptions } from "@/features/schedules/api/get-schedule"
import { scheduleTitle } from "@/features/schedules/format"
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
  const detail = conversationQuery.data
  if (!detail || detail.access === "viewer") return null
  const conversation = {
    ...(streamConversation ?? detail),
    ...(detail.visibility ? { visibility: detail.visibility } : {}),
    ...(detail.capabilities ? { capabilities: detail.capabilities } : {}),
  }

  return (
    <ConversationDetail
      key={conversationId}
      conversation={conversation}
      conversationId={conversationId}
    />
  )
}

function ConversationDetail({
  conversation,
  conversationId,
}: {
  conversation: Conversation
  conversationId: string
}) {
  const scheduleContext =
    conversation.source === "scheduled" ? conversationScheduleContext(conversation.metadata) : null
  const scheduleQuery = useQuery({
    ...scheduleQueryOptions(scheduleContext?.scheduleId ?? ""),
    enabled: scheduleContext?.scheduleId !== null && scheduleContext !== null,
  })
  const { pendingUserMessages, stream } = useConversationWorkspace()
  const [submittingApprovalRunId, setSubmittingApprovalRunId] = useState<string | null>(null)
  const isLiveStreamConversation = stream.conversationId === conversationId
  const streamConnected = isLiveStreamConversation && stream.isConnected
  const streamActiveRun = isLiveStreamConversation
    ? streamActiveRunFromState({
        conversation,
        done: stream.done,
        runId: stream.runId,
        status: stream.status,
      })
    : undefined
  const initialActiveRun =
    isLiveStreamConversation && streamActiveRun !== undefined
      ? ({
          active_run: streamActiveRun,
          latest_run: null,
          approval_expires_at: null,
        } satisfies ConversationActiveRunResponse)
      : undefined
  const recovery = useConversationRecovery(conversationId, streamConnected, initialActiveRun)
  const { messagesQuery, activeRunQuery, approvalStateQuery } = recovery
  const messages = messagesQuery.data?.messages ?? EMPTY_CONVERSATION_MESSAGES.messages
  const activeRun = resolveConversationActiveRun(
    activeRunQuery.data?.active_run,
    streamActiveRun,
    streamConnected
  )
  const latestRun = activeRunQuery.data?.latest_run ?? null
  const runInterruption = conversationRunInterruptionOutcome(activeRun, latestRun)
  const transcriptRun = activeRun ?? (runInterruption ? latestRun : null)
  const [agentQuery, modelCatalogQuery] = useSuspenseQueries({
    queries: [agentQueryOptions(conversation.active_agent_id ?? ""), modelCatalogQueryOptions()],
  })
  const activeRunId = activeRun?.id ?? null
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
    latestRun,
    conversationId,
    messages,
    recoveredApprovals: approvalStateQuery.data?.approvals ?? [],
    recoveredDelegations: approvalStateQuery.data?.delegations ?? [],
    stream,
    submittingApprovalRunId,
  })
  const approvalRevision =
    activeRunQuery.data?.approval_revision ??
    (stream.runId === activeRunId ? stream.approvalRevision : null) ??
    approvalStateQuery.data?.approval_revision ??
    null
  const proposalRevision = approvalStateQuery.data?.approvals.length
    ? approvalStateQuery.data.approval_revision
    : stream.runId === activeRunId
      ? stream.approvalRevision
      : null
  const approvalReady =
    !recovery.approvalUnavailable &&
    approvalBatchIsReady({
      currentRevision: approvalRevision,
      proposalRevision,
      hasRecoveredBatch:
        approvalStateQuery.data?.run_id === activeRunId &&
        approvalStateQuery.data.approvals.length > 0,
      streamBatchComplete: stream.runId === activeRunId && stream.approvalBatchComplete,
    })
  const assistantLabel = conversationAgentLabel(conversation, "Agent")
  const assistantAgentId = activeRun?.agent_id ?? conversation.active_agent_id ?? "unassigned-agent"
  const assistantAgentMetadata =
    agentQuery.data.id === assistantAgentId ? agentQuery.data.metadata : null
  const timeline = useMemo(
    () =>
      projectConversationTimeline({
        approvals: pendingApprovals,
        assistantAgentId,
        conversationId,
        messages,
        pendingDelegations,
        pendingUserMessages,
        pendingWorkflow:
          approvalStateQuery.data?.workflow ??
          approvalStateQuery.data?.workflows?.find(
            (workflow) => workflow.owner_run_id === activeRunId
          ) ??
          null,
        pendingWorkflows: approvalStateQuery.data?.workflows ?? [],
        approvalRevision,
        readOnly:
          conversation.source === "delegated" ||
          Boolean(activeRun?.parent_run_id) ||
          !approvalReady,
        stream: {
          approvals: visibleStreamApprovals,
          conversationId: shouldRenderStream ? stream.conversationId : null,
          isStreaming: shouldRenderStream && stream.isStreaming,
          messages: streamMessages,
          runId: shouldRenderStream ? stream.runId : null,
          toolCalls: streamToolCalls,
        },
        transcriptRun,
      }),
    [
      approvalStateQuery.data?.workflow,
      approvalStateQuery.data?.workflows,
      approvalRevision,
      approvalReady,
      activeRunId,
      activeRun?.parent_run_id,
      conversation.source,
      assistantAgentId,
      conversationId,
      messages,
      pendingApprovals,
      pendingDelegations,
      pendingUserMessages,
      shouldRenderStream,
      stream.conversationId,
      stream.isStreaming,
      stream.runId,
      streamMessages,
      streamToolCalls,
      transcriptRun,
      visibleStreamApprovals,
    ]
  )
  const pendingMessageCount = timeline.rows.filter((row) => row.kind === "pending-message").length
  const { handleScroll, isAwayFromBottom, scrollRef, scrollToBottom } = useConversationAutoScroll({
    approvalCount: pendingApprovals.length,
    messageCount: messages.length,
    pendingMessageCount,
    streamMessages,
    streamToolCalls,
  })

  useConversationReadReceipt({
    conversationId,
    unread: conversation.unread,
  })

  const composerDisabledReason =
    recovery.error || !activeRunQuery.data
      ? "Wait for the conversation to refresh before sending a message."
      : getConversationComposerDisabledReason(activeRun)
  const approvalError = approvalStateQuery.error ? getErrorMessage(approvalStateQuery.error) : null
  const isResumingRun = activeRunId !== null && submittingApprovalRunId === activeRunId
  const isReadOnlyTranscript = conversation.source === "delegated"
  const showScrollToBottom = shouldRenderStream && stream.isStreaming && isAwayFromBottom

  async function handleApprovalSubmit(decisions: AgentRunResumeDecision[], revision?: string) {
    if (isReadOnlyTranscript || activeRun?.parent_run_id) {
      throw new Error("Review these requests in the main conversation.")
    }
    if (!approvalReady || revision !== (approvalRevision ?? undefined)) {
      throw new Error("These requests have changed. Refresh and review them again.")
    }
    if (!activeRun) {
      return
    }

    const runId = activeRun.id
    setSubmittingApprovalRunId(runId)
    try {
      await reconcileApprovalSubmission(
        () =>
          stream.resumeRun({
            runId,
            payload: { decisions, ...(revision ? { approval_revision: revision } : {}) },
          }),
        recovery.refresh
      )
    } finally {
      setSubmittingApprovalRunId((currentRunId) => (currentRunId === runId ? null : currentRunId))
    }
  }

  return (
    <div className="bg-background flex h-full min-h-0 min-w-0 flex-col overflow-hidden">
      <div className="shrink-0">
        <ConversationDetailHeader
          activeRun={activeRun}
          conversation={conversation}
          scheduleLabel={scheduleQuery.data ? scheduleTitle(scheduleQuery.data) : null}
        />
      </div>
      <Separator className="shrink-0" />

      <div className="relative min-h-0 flex-1">
        <div ref={scrollRef} className="h-full overflow-y-auto" onScroll={handleScroll}>
          <div className="mx-auto w-full max-w-4xl px-6 py-6 pb-8">
            {recovery.error || recovery.refreshing || recovery.paused ? (
              <Alert role="status" className="mb-4">
                <AlertDescription>
                  {recovery.paused
                    ? "Waiting for a connection…"
                    : recovery.refreshing
                      ? "Refreshing the conversation…"
                      : conversationRecoveryMessage(recovery.error)}
                </AlertDescription>
                <AlertAction>
                  <Button
                    size="sm"
                    variant="outline"
                    disabled={recovery.refreshing || recovery.paused}
                    onClick={() => {
                      void recovery.refresh().catch(() => undefined)
                    }}
                  >
                    Retry
                  </Button>
                </AlertAction>
              </Alert>
            ) : null}
            {messagesQuery.data || shouldRenderStream ? (
              <MessageList
                approvalError={approvalError}
                runInterruption={runInterruption}
                assistantAgentMetadata={assistantAgentMetadata}
                assistantLabel={assistantLabel}
                conversationId={conversationId}
                isApprovalLoading={approvalStateQuery.isLoading}
                isApprovalSubmitting={isResumingRun}
                onApprovalSubmit={handleApprovalSubmit}
                streamError={streamError}
                timeline={timeline}
              />
            ) : null}
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
            {activeRunQuery.data?.root_conversation_id ? (
              <Link
                to="/conversations/$conversationId"
                params={{ conversationId: activeRunQuery.data.root_conversation_id }}
              >
                Open main conversation
              </Link>
            ) : null}
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
