// apps/web/src/features/conversations/components/message-list.tsx

import { approvalActivityIdentity } from "@/lib/tool-activity-identity"

import { MessageSquareTextIcon } from "lucide-react"

import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert"
import { ToolApprovalLoadingCard } from "@/components/tool-ui/approval-card"
import { ApprovalDecisionContext } from "@/features/conversations/approval-decision-context"
import {
  SharedTranscriptContext,
  ToolConversationContext,
} from "@/components/tool-ui/tool-conversation-context"
import { AssistantMessageShell } from "@/features/conversations/components/message-shell"
import {
  AssistantLiveActivityRow,
  AssistantTurnRow,
  MessageRow,
} from "@/features/conversations/components/message-row"
import { ToolCallRow } from "@/features/conversations/components/tool-call-row"
import { useInlineApprovals } from "@/features/conversations/hooks/use-inline-approvals"
import { useReviewApprovalMutation } from "@/features/conversations/api/review-approval"
import { useToolPresentations } from "@/features/tools/use-tool-presentations"
import { RunOutcomeAlert } from "@/features/conversations/components/run-outcome-alert"
import type { RunInterruptionOutcome } from "@/features/conversations/run-error-copy"
import type { AgentRunResumeDecision } from "@/features/conversations/types"
import type {
  ConversationTimeline,
  ConversationTimelineRow,
} from "@/features/conversations/message-parts/timeline"

type TranscriptProps = {
  timeline: ConversationTimeline
  assistantAgentMetadata: Record<string, unknown> | null
  assistantLabel: string
}

type MessageListProps = TranscriptProps & {
  conversationId: string
  approvalError: string | null
  runInterruption: RunInterruptionOutcome | null
  isApprovalLoading: boolean
  isApprovalSubmitting: boolean
  streamError?: string | null
  onApprovalSubmit: (decisions: AgentRunResumeDecision[], revision?: string) => Promise<void>
}

export function MessageList(
  props: (MessageListProps & { shared?: false }) | (TranscriptProps & { shared: true })
) {
  if (props.shared) {
    return (
      <SharedTranscriptContext value>
        <ToolConversationContext value={null}>
          <div className="flex min-w-0 flex-col gap-7">
            <TranscriptRows {...props} />
          </div>
        </ToolConversationContext>
      </SharedTranscriptContext>
    )
  }
  return <InteractiveMessageList {...props} />
}

function InteractiveMessageList({
  conversationId,
  timeline,
  approvalError,
  runInterruption,
  assistantAgentMetadata,
  assistantLabel,
  isApprovalLoading,
  isApprovalSubmitting,
  streamError,
  onApprovalSubmit,
}: MessageListProps) {
  const presentationFor = useToolPresentations()
  const reviewApproval = useReviewApprovalMutation(conversationId)
  const inlineApprovals = useInlineApprovals({
    activeRunId: timeline.approval?.runId ?? null,
    approvalRevision: timeline.approval?.revision ?? null,
    readOnly: timeline.approval?.readOnly ?? false,
    approvals: timeline.approval?.requests ?? [],
    enabled: timeline.approval !== null,
    isSubmitting: isApprovalSubmitting,
    onSubmit: onApprovalSubmit,
    onReview: reviewApproval.mutateAsync,
    presentationFor,
  })
  const approvalErrorMessage = approvalError ?? inlineApprovals.unavailableReason
  const hasInlineApprovals =
    timeline.approval !== null &&
    (timeline.approval.requests.length > 0 || isApprovalLoading || Boolean(approvalError))
  const hasMessages =
    timeline.rows.length > 0 || hasInlineApprovals || timeline.liveActivity !== null

  if (!hasMessages && !runInterruption) {
    return (
      <div className="flex min-h-80 flex-col items-center justify-center p-8 text-center">
        <div className="bg-muted text-muted-foreground mb-4 flex size-10 items-center justify-center rounded-full">
          <MessageSquareTextIcon className="size-5" />
        </div>
        <h2 className="font-heading text-lg font-medium">No messages yet</h2>
        <p className="text-muted-foreground mt-2 max-w-sm text-sm">
          Send the first prompt to start this conversation.
        </p>
      </div>
    )
  }

  return (
    <ToolConversationContext value={conversationId}>
      <ApprovalDecisionContext value={inlineApprovals.resolveApprovalControls}>
        <div className="flex min-w-0 flex-col gap-7">
          <TranscriptRows
            timeline={timeline}
            assistantAgentMetadata={assistantAgentMetadata}
            assistantLabel={assistantLabel}
          />

          {timeline.liveActivity ? (
            <AssistantLiveActivityRow
              assistantAgentId={timeline.assistantAgentId}
              assistantAgentMetadata={assistantAgentMetadata}
              assistantLabel={assistantLabel}
              isStreaming={timeline.liveActivity.isStreaming}
              messages={timeline.liveActivity.messages}
              timeline={timeline.liveActivity.timeline}
            />
          ) : null}

          {timeline.orphanApprovals.length > 0 && (
            <AssistantMessageShell
              agentId={timeline.assistantAgentId}
              agentMetadata={assistantAgentMetadata}
              createdAt={null}
              label={assistantLabel}
            >
              {timeline.orphanApprovals.map((activity) => (
                <ToolCallRow activity={activity} key={approvalActivityIdentity(activity)} />
              ))}
            </AssistantMessageShell>
          )}

          {timeline.approval && approvalErrorMessage && (
            <div className="pl-10">
              <Alert variant="destructive">
                <AlertTitle>Approval state unavailable</AlertTitle>
                <AlertDescription>{approvalErrorMessage}</AlertDescription>
              </Alert>
            </div>
          )}

          {timeline.approval && isApprovalLoading && timeline.approval.requests.length === 0 && (
            <div className="pl-10">
              <ToolApprovalLoadingCard />
            </div>
          )}

          {runInterruption && <RunOutcomeAlert outcome={runInterruption} />}

          {streamError && streamError !== runInterruption?.message && (
            <div className="w-full px-1 py-2">
              <Alert variant="destructive">
                <AlertTitle>Stream failed</AlertTitle>
                <AlertDescription>{streamError}</AlertDescription>
              </Alert>
            </div>
          )}
        </div>
      </ApprovalDecisionContext>
    </ToolConversationContext>
  )
}

function TranscriptRows({ timeline, assistantAgentMetadata, assistantLabel }: TranscriptProps) {
  return timeline.rows.map((item) => (
    <TranscriptRenderItem
      key={item.id}
      assistantAgentId={timeline.assistantAgentId}
      assistantAgentMetadata={assistantAgentMetadata}
      assistantLabel={assistantLabel}
      item={item}
    />
  ))
}

function TranscriptRenderItem({
  assistantAgentId,
  assistantAgentMetadata,
  assistantLabel,
  item,
}: {
  assistantAgentId: string
  assistantAgentMetadata: Record<string, unknown> | null
  assistantLabel: string
  item: ConversationTimelineRow
}) {
  if (item.kind === "run-outcome") {
    return <RunOutcomeAlert outcome={item.outcome} />
  }
  if (item.kind === "pending-message") {
    return (
      <MessageRow
        assistantAgentId={assistantAgentId}
        assistantAgentMetadata={assistantAgentMetadata}
        pendingMessage={item.message}
      />
    )
  }
  if (item.kind === "assistant-turn") {
    return (
      <AssistantTurnRow
        assistantAgentId={assistantAgentId}
        assistantAgentMetadata={assistantAgentMetadata}
        assistantLabel={assistantLabel}
        createdAt={item.createdAt}
        messages={item.messages}
      />
    )
  }

  return (
    <MessageRow
      assistantAgentId={assistantAgentId}
      assistantAgentMetadata={assistantAgentMetadata}
      assistantLabel={assistantLabel}
      message={item.message}
    />
  )
}
