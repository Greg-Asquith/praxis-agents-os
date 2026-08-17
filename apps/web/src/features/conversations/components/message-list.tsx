// apps/web/src/features/conversations/components/message-list.tsx

import { useMemo } from "react"
import { MessageSquareTextIcon } from "lucide-react"

import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert"
import { ApprovalDecisionContext } from "@/features/conversations/approval-decision-context"
import { ToolConversationContext } from "@/components/tool-ui/tool-conversation-context"
import { AssistantMessageShell } from "@/features/conversations/components/message-shell"
import {
  AssistantLiveActivityRow,
  AssistantTurnRow,
  MessageRow,
  type AssistantLiveTimelinePart,
} from "@/features/conversations/components/message-row"
import { ToolCallRow } from "@/features/conversations/components/tool-call-row"
import { useInlineApprovals } from "@/features/conversations/hooks/use-inline-approvals"
import { useToolPresentations } from "@/features/tools/use-tool-presentations"
import { useToolLabels } from "@/features/tools/use-tool-labels"
import type { RunInterruptionOutcome } from "@/features/conversations/run-error-copy"
import type {
  AgentRun,
  AgentRunResumeDecision,
  ConversationMessage,
  PendingDelegatedApproval,
  PendingWorkflowState,
  PendingToolApproval,
} from "@/features/conversations/types"
import {
  selectLiveTimeline,
  type ApprovalState,
  type ChatMessageDraft,
  type ToolCallState,
} from "@/features/conversations/stream/reducer"
import { shouldShowLiveActivity } from "@/features/conversations/live-activity-visibility"
import { buildLiveToolActivities } from "@/features/conversations/live-tool-activities"
import {
  groupConversationRenderItems,
  parseConversationMessages,
  delegationDetailsForToolActivity,
  delegationDetailsForPendingApproval,
  normalizeToolArgs,
  toolActivityIdentity,
  type ConversationRenderItem,
  type LiveToolResult,
  type PendingUserMessage,
  type ToolActivity,
} from "@/features/conversations/message-parts"

type MessageListProps = {
  conversationId: string
  messages: ConversationMessage[]
  activeRun: AgentRun | null
  approvalError: string | null
  runInterruption: RunInterruptionOutcome | null
  approvals: PendingToolApproval[]
  assistantAgentId: string
  assistantAgentMetadata: Record<string, unknown> | null
  assistantLabel: string
  isApprovalLoading: boolean
  isApprovalSubmitting: boolean
  pendingUserMessages: PendingUserMessage[]
  streamMessages: ChatMessageDraft[]
  streamToolCalls: ToolCallState[]
  streamApprovals: ApprovalState[]
  streamError?: string | null
  streamConversationId: string | null
  streamRunId: string | null
  isStreaming: boolean
  onApprovalSubmit: (decisions: AgentRunResumeDecision[]) => Promise<void>
  pendingDelegations: PendingDelegatedApproval[]
  pendingWorkflow: PendingWorkflowState | null
}

export function MessageList({
  conversationId,
  messages,
  activeRun,
  approvalError,
  runInterruption,
  approvals,
  assistantAgentId,
  assistantAgentMetadata,
  pendingDelegations,
  pendingWorkflow,
  assistantLabel,
  isApprovalLoading,
  isApprovalSubmitting,
  pendingUserMessages,
  streamMessages,
  streamToolCalls,
  streamApprovals,
  streamError,
  streamConversationId,
  streamRunId,
  isStreaming,
  onApprovalSubmit,
}: MessageListProps) {
  const toolLabel = useToolLabels()
  const shouldShowStream = streamConversationId === conversationId
  const liveResultsByCallIdentity = useMemo(() => {
    const results = new Map<string, LiveToolResult>()
    if (!shouldShowStream) {
      return results
    }
    for (const toolCall of streamToolCalls) {
      if (toolCall.status === "awaiting_approval") {
        continue
      }
      results.set(toolActivityIdentity(streamRunId, toolCall.tool_call_id), {
        result: toolCall.result,
        status: toolCall.status,
      })
    }
    return results
  }, [shouldShowStream, streamRunId, streamToolCalls])
  const parsedMessages = useMemo(
    () =>
      parseConversationMessages(
        messages,
        activeRun,
        pendingDelegations,
        liveResultsByCallIdentity,
        pendingWorkflow
      ),
    [messages, activeRun, pendingDelegations, liveResultsByCallIdentity, pendingWorkflow]
  )
  const renderItems = useMemo(() => groupConversationRenderItems(parsedMessages), [parsedMessages])
  const visiblePendingUserMessages = pendingUserMessages
  const transcriptToolIds = useMemo(
    () =>
      new Set(
        parsedMessages.flatMap((message) =>
          message.toolActivities.map((activity) =>
            toolActivityIdentity(activity.agentRunId, activity.id)
          )
        )
      ),
    [parsedMessages]
  )
  const liveToolActivities = useMemo(
    () => buildLiveToolActivities(streamToolCalls, streamApprovals, streamRunId),
    [streamToolCalls, streamApprovals, streamRunId]
  )
  const liveTimeline = useMemo(() => {
    const activitiesById = new Map(
      liveToolActivities.map((activity) => [activity.id, activity] as const)
    )
    return selectLiveTimeline(streamMessages, streamToolCalls).flatMap(
      (item): AssistantLiveTimelinePart[] => {
        if (item.kind === "text") {
          return [{ kind: "text", message: item.message }]
        }
        // A tool already rendered in the transcript (a resumed approval, or a
        // mid-run refetch) must not render twice in the live area.
        if (transcriptToolIds.has(toolActivityIdentity(streamRunId, item.toolCall.tool_call_id))) {
          return []
        }
        const activity = activitiesById.get(item.toolCall.tool_call_id)
        return activity ? [{ kind: "tool", activity }] : []
      }
    )
  }, [liveToolActivities, streamMessages, streamRunId, streamToolCalls, transcriptToolIds])
  const hasRunningTranscriptTool = parsedMessages.some((message) =>
    message.toolActivities.some((activity) => activity.status === "running")
  )
  const showLiveActivity =
    shouldShowStream &&
    shouldShowLiveActivity({
      hasRunningTranscriptTool,
      isStreaming,
      liveMessageCount: streamMessages.length,
      liveToolActivityCount: liveToolActivities.length,
    })
  const isAwaitingApproval = activeRun?.status === "awaiting_approval"
  const presentationFor = useToolPresentations()
  const inlineApprovals = useInlineApprovals({
    activeRunId: activeRun?.id ?? null,
    approvals,
    enabled: isAwaitingApproval,
    isSubmitting: isApprovalSubmitting,
    onSubmit: onApprovalSubmit,
    presentationFor,
  })
  // Approvals whose tool call is not in the transcript yet (for example while the paused run's messages are still refetching) fall back to standalone rows.
  const orphanApprovalActivities = useMemo(() => {
    if (!isAwaitingApproval) {
      return []
    }
    const renderedAwaitingIds = new Set(
      [...parsedMessages.flatMap((message) => message.toolActivities), ...liveToolActivities]
        .flatMap((activity) => [activity, ...(activity.script?.children ?? [])])
        .filter((activity) => activity.status === "awaiting_approval")
        .map((activity) => toolActivityIdentity(activity.agentRunId, activity.id))
    )
    return approvals
      .filter(
        (approval) =>
          !renderedAwaitingIds.has(toolActivityIdentity(activeRun.id, approval.tool_call_id))
      )
      .map((approval) => orphanApprovalActivity(approval, activeRun.id))
  }, [activeRun, approvals, isAwaitingApproval, liveToolActivities, parsedMessages])
  const hasInlineApprovals =
    isAwaitingApproval && (approvals.length > 0 || isApprovalLoading || Boolean(approvalError))
  const hasMessages =
    parsedMessages.length > 0 ||
    visiblePendingUserMessages.length > 0 ||
    hasInlineApprovals ||
    showLiveActivity

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
          {renderItems.map((item) => (
            <TranscriptRenderItem
              key={item.id}
              assistantAgentId={assistantAgentId}
              assistantAgentMetadata={assistantAgentMetadata}
              assistantLabel={assistantLabel}
              item={item}
            />
          ))}

          {visiblePendingUserMessages.map((message) => (
            <MessageRow
              key={message.clientMessageId}
              assistantAgentId={assistantAgentId}
              assistantAgentMetadata={assistantAgentMetadata}
              pendingMessage={message}
            />
          ))}

          {showLiveActivity && (
            <AssistantLiveActivityRow
              assistantAgentId={assistantAgentId}
              assistantAgentMetadata={assistantAgentMetadata}
              assistantLabel={assistantLabel}
              isStreaming={isStreaming}
              messages={streamMessages}
              timeline={liveTimeline}
            />
          )}

          {orphanApprovalActivities.length > 0 && (
            <AssistantMessageShell
              agentId={assistantAgentId}
              agentMetadata={assistantAgentMetadata}
              createdAt={null}
              label={assistantLabel}
            >
              {orphanApprovalActivities.map((activity) => (
                <ToolCallRow activity={activity} key={activity.id} />
              ))}
            </AssistantMessageShell>
          )}

          {isAwaitingApproval && approvalError && (
            <div className="pl-10">
              <Alert variant="destructive">
                <AlertTitle>Approval state unavailable</AlertTitle>
                <AlertDescription>{approvalError}</AlertDescription>
              </Alert>
            </div>
          )}

          {isAwaitingApproval && isApprovalLoading && approvals.length === 0 && (
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
  item: ConversationRenderItem
}) {
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

function orphanApprovalActivity(
  approval: PendingToolApproval,
  agentRunId: string | null
): ToolActivity {
  const args = normalizeToolArgs(approval.args)
  const activity: ToolActivity = {
    id: approval.tool_call_id,
    agentRunId,
    kind: "approval",
    status: "awaiting_approval",
    name: approval.name,
    args,
    ...(approval.derived_from_untrusted === true ? { derivedFromUntrusted: true } : {}),
    ...(approval.taint_sources === undefined ? {} : { taintSources: approval.taint_sources }),
  }
  const delegate = approval.delegation
    ? delegationDetailsForPendingApproval(approval.delegation, args)
    : delegationDetailsForToolActivity(approval.name, args)
  if (delegate) {
    activity.delegate = delegate
  }
  return activity
}
