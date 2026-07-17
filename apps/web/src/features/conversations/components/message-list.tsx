// apps/web/src/features/conversations/components/message-list.tsx

import { useMemo } from "react"
import { MessageSquareTextIcon } from "lucide-react"

import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert"
import { ApprovalDecisionContext } from "@/features/conversations/approval-decision-context"
import { AssistantMessageShell } from "@/features/conversations/components/message-shell"
import {
  AssistantLiveActivityRow,
  AssistantTurnRow,
  MessageRow,
  type AssistantLiveTimelinePart,
} from "@/features/conversations/components/message-row"
import { ToolCallRow } from "@/features/conversations/components/tool-call-row"
import { useInlineApprovals } from "@/features/conversations/hooks/use-inline-approvals"
import type {
  AgentRun,
  AgentRunResumeDecision,
  ConversationMessage,
  PendingDelegatedApproval,
  PendingToolApproval,
} from "@/features/conversations/types"
import {
  selectLiveTimeline,
  type ApprovalState,
  type ChatMessageDraft,
  type ToolCallState,
} from "@/features/conversations/stream/reducer"
import { LOAD_CAPABILITY_TOOL_NAME } from "@/features/conversations/skill-activation"
import { shouldShowLiveActivity } from "@/features/conversations/live-activity-visibility"
import {
  groupConversationRenderItems,
  parseConversationMessages,
  delegationDetailsForToolActivity,
  delegationDetailsForPendingApproval,
  mergeDelegationDetails,
  normalizeToolArgs,
  type ConversationRenderItem,
  type PendingUserMessage,
  type ToolActivity,
} from "@/features/conversations/message-parts"

type MessageListProps = {
  conversationId: string
  messages: ConversationMessage[]
  activeRun: AgentRun | null
  approvalError: string | null
  approvals: PendingToolApproval[]
  assistantAgentId: string
  assistantLabel: string
  isApprovalLoading: boolean
  isApprovalSubmitting: boolean
  pendingUserMessages: PendingUserMessage[]
  streamMessages: ChatMessageDraft[]
  streamToolCalls: ToolCallState[]
  streamApprovals: ApprovalState[]
  streamError?: string | null
  streamConversationId: string | null
  isStreaming: boolean
  onApprovalSubmit: (decisions: AgentRunResumeDecision[]) => Promise<void>
  pendingDelegations: PendingDelegatedApproval[]
}

export function MessageList({
  conversationId,
  messages,
  activeRun,
  approvalError,
  approvals,
  assistantAgentId,
  pendingDelegations,
  assistantLabel,
  isApprovalLoading,
  isApprovalSubmitting,
  pendingUserMessages,
  streamMessages,
  streamToolCalls,
  streamApprovals,
  streamError,
  streamConversationId,
  isStreaming,
  onApprovalSubmit,
}: MessageListProps) {
  const parsedMessages = useMemo(
    () => parseConversationMessages(messages, activeRun?.status, pendingDelegations),
    [messages, activeRun?.status, pendingDelegations]
  )
  const renderItems = useMemo(() => groupConversationRenderItems(parsedMessages), [parsedMessages])
  const visiblePendingUserMessages = pendingUserMessages
  const shouldShowStream = streamConversationId === conversationId
  const liveToolActivities = useMemo(
    () => buildLiveToolActivities(streamToolCalls, streamApprovals),
    [streamToolCalls, streamApprovals]
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
        const activity = activitiesById.get(item.toolCall.tool_call_id)
        return activity ? [{ kind: "tool", activity }] : []
      }
    )
  }, [liveToolActivities, streamMessages, streamToolCalls])
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
  const inlineApprovals = useInlineApprovals({
    approvals,
    enabled: isAwaitingApproval,
    isSubmitting: isApprovalSubmitting,
    onSubmit: onApprovalSubmit,
  })
  // Approvals whose tool call is not in the transcript yet (for example while the paused run's messages are still refetching) fall back to standalone rows.
  const orphanApprovalActivities = useMemo(() => {
    if (!isAwaitingApproval) {
      return []
    }
    const renderedAwaitingIds = new Set(
      [...parsedMessages.flatMap((message) => message.toolActivities), ...liveToolActivities]
        .filter((activity) => activity.status === "awaiting_approval")
        .map((activity) => activity.id)
    )
    return approvals
      .filter((approval) => !renderedAwaitingIds.has(approval.tool_call_id))
      .map(orphanApprovalActivity)
  }, [approvals, isAwaitingApproval, liveToolActivities, parsedMessages])
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
    <ApprovalDecisionContext value={inlineApprovals.resolveApprovalControls}>
      <div className="flex min-w-0 flex-col gap-7">
        {renderItems.map((item) => (
          <TranscriptRenderItem
            key={item.id}
            assistantAgentId={assistantAgentId}
            assistantLabel={assistantLabel}
            item={item}
          />
        ))}

        {visiblePendingUserMessages.map((message) => (
          <MessageRow
            key={message.clientMessageId}
            assistantAgentId={assistantAgentId}
            pendingMessage={message}
          />
        ))}

        {showLiveActivity && (
          <AssistantLiveActivityRow
            assistantAgentId={assistantAgentId}
            assistantLabel={assistantLabel}
            isStreaming={isStreaming}
            messages={streamMessages}
            timeline={liveTimeline}
          />
        )}

        {orphanApprovalActivities.length > 0 && (
          <AssistantMessageShell agentId={assistantAgentId} createdAt={null} label={assistantLabel}>
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
  )
}

function TranscriptRenderItem({
  assistantAgentId,
  assistantLabel,
  item,
}: {
  assistantAgentId: string
  assistantLabel: string
  item: ConversationRenderItem
}) {
  if (item.kind === "assistant-turn") {
    return (
      <AssistantTurnRow
        assistantAgentId={assistantAgentId}
        assistantLabel={assistantLabel}
        createdAt={item.createdAt}
        messages={item.messages}
      />
    )
  }

  return (
    <MessageRow
      assistantAgentId={assistantAgentId}
      assistantLabel={assistantLabel}
      message={item.message}
    />
  )
}

function orphanApprovalActivity(approval: PendingToolApproval): ToolActivity {
  const args = normalizeToolArgs(approval.args)
  const activity: ToolActivity = {
    id: approval.tool_call_id,
    kind: "approval",
    status: "awaiting_approval",
    name: approval.name,
    args,
  }
  const delegate = approval.delegation
    ? delegationDetailsForPendingApproval(approval.delegation, args)
    : delegationDetailsForToolActivity(approval.name, args)
  if (delegate) {
    activity.delegate = delegate
  }
  return activity
}

function buildLiveToolActivities(
  toolCalls: ToolCallState[],
  approvals: ApprovalState[]
): ToolActivity[] {
  const activities = toolCalls.map((toolCall): ToolActivity => {
    const args = normalizeToolArgs(toolCall.args)
    const activity: ToolActivity = {
      id: toolCall.tool_call_id,
      kind: toolCall.status === "awaiting_approval" ? "approval" : "call",
      status: toolCall.status,
      name: toolCall.name,
      args,
      result: toolCall.result,
      ...(toolCall.name === LOAD_CAPABILITY_TOOL_NAME ? { toolKind: "capability-load" } : {}),
    }
    const delegate = delegationDetailsForToolActivity(toolCall.name, args, toolCall.result)
    if (delegate) {
      activity.delegate = delegate
    }
    return activity
  })
  const activityIndexesById = new Map(activities.map((activity, index) => [activity.id, index]))

  for (const delegation of approvals
    .map((approval) => approval.delegation)
    .filter((value): value is PendingDelegatedApproval => Boolean(value))) {
    const existingIndex = activityIndexesById.get(delegation.parent_tool_call_id)
    if (existingIndex === undefined) {
      activities.push({
        id: delegation.parent_tool_call_id,
        kind: "approval",
        status: "awaiting_approval",
        name: "delegate_to_agent",
        delegate: delegationDetailsForPendingApproval(delegation),
      })
      activityIndexesById.set(delegation.parent_tool_call_id, activities.length - 1)
      continue
    }

    const existing = activities[existingIndex]
    if (existing === undefined) {
      continue
    }
    const pendingDelegate = delegationDetailsForPendingApproval(delegation, existing.args)
    const delegate = mergeDelegationDetails(existing.delegate, pendingDelegate) ?? pendingDelegate
    activities[existingIndex] = {
      ...existing,
      delegate,
      kind: "approval",
      status: "awaiting_approval",
    }
  }

  for (const approval of approvals) {
    if (activities.some((activity) => activity.id === approval.tool_call_id)) {
      continue
    }

    const args = normalizeToolArgs(approval.args)
    const activity: ToolActivity = {
      id: approval.tool_call_id,
      kind: "approval",
      status: "awaiting_approval",
      name: approval.name,
      args,
    }
    const delegate = delegationDetailsForToolActivity(approval.name, args)
    if (delegate) {
      activity.delegate = delegate
    }
    activities.push(activity)
  }

  return activities
}
