// apps/web/src/features/conversations/components/message-list.tsx

import { MessageSquareTextIcon } from "lucide-react"

import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert"
import { ApprovalDecisionContext } from "@/features/conversations/approval-decision-context"
import { ToolConversationContext } from "@/components/tool-ui/tool-conversation-context"
import { AssistantMessageShell } from "@/features/conversations/components/message-shell"
import {
  AssistantLiveActivityRow,
  AssistantTurnRow,
  MessageRow,
} from "@/features/conversations/components/message-row"
import { ToolCallRow } from "@/features/conversations/components/tool-call-row"
import { useInlineApprovals } from "@/features/conversations/hooks/use-inline-approvals"
import { useToolPresentations } from "@/features/tools/use-tool-presentations"
import { useToolLabels } from "@/features/tools/use-tool-labels"
import type { RunInterruptionOutcome } from "@/features/conversations/run-error-copy"
import type { AgentRunResumeDecision } from "@/features/conversations/types"
import type {
  ConversationTimeline,
  ConversationTimelineRow,
} from "@/features/conversations/message-parts/timeline"

type MessageListProps = {
  conversationId: string
  timeline: ConversationTimeline
  approvalError: string | null
  runInterruption: RunInterruptionOutcome | null
  assistantAgentMetadata: Record<string, unknown> | null
  assistantLabel: string
  isApprovalLoading: boolean
  isApprovalSubmitting: boolean
  streamError?: string | null
  onApprovalSubmit: (decisions: AgentRunResumeDecision[]) => Promise<void>
}

export function MessageList({
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
  const toolLabel = useToolLabels()
  const presentationFor = useToolPresentations()
  const inlineApprovals = useInlineApprovals({
    activeRunId: timeline.approval?.runId ?? null,
    approvals: timeline.approval?.requests ?? [],
    enabled: timeline.approval !== null,
    isSubmitting: isApprovalSubmitting,
    onSubmit: onApprovalSubmit,
    presentationFor,
  })
  const hasInlineApprovals =
    timeline.approval !== null &&
    (timeline.approval.requests.length > 0 || isApprovalLoading || Boolean(approvalError))
  const hasMessages =
    timeline.rows.length > 0 || hasInlineApprovals || timeline.liveActivity !== null

  if (!hasMessages) {
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
          {timeline.rows.map((item) => (
            <TranscriptRenderItem
              key={item.id}
              assistantAgentId={timeline.assistantAgentId}
              assistantAgentMetadata={assistantAgentMetadata}
              assistantLabel={assistantLabel}
              item={item}
            />
          ))}

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
                <ToolCallRow activity={activity} key={activity.id} />
              ))}
            </AssistantMessageShell>
          )}

          {timeline.approval && approvalError && (
            <div className="pl-10">
              <Alert variant="destructive">
                <AlertTitle>Approval state unavailable</AlertTitle>
                <AlertDescription>{approvalError}</AlertDescription>
              </Alert>
            </div>
          )}

          {timeline.approval && isApprovalLoading && timeline.approval.requests.length === 0 && (
            <p className="text-muted-foreground pl-10 text-sm">Loading approval requests.</p>
          )}

          {runInterruption && (
            <div className="w-full px-1 py-2">
              <Alert variant="destructive">
                <AlertTitle>{runInterruption.title}</AlertTitle>
                <AlertDescription>
                  <p>{runInterruption.message}</p>
                  {runInterruption.completedActions.length > 0 ? (
                    <div className="mt-2">
                      <p className="font-medium">Completed Actions</p>
                      <ul className="mt-1 list-disc space-y-0.5 pl-5">
                        {runInterruption.completedActions.map((action) => (
                          <li key={action.id}>{toolLabel(action.toolName)}</li>
                        ))}
                      </ul>
                      {runInterruption.actionsTruncated ? (
                        <p className="mt-1">More completed actions are recorded in the run.</p>
                      ) : null}
                    </div>
                  ) : null}
                </AlertDescription>
              </Alert>
            </div>
          )}

          {streamError && (
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
