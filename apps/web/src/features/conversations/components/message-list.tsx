// apps/web/src/features/conversations/components/message-list.tsx

import { useMemo } from "react"
import { MessageSquareTextIcon } from "lucide-react"

import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert"
import { ApprovalControls } from "@/features/conversations/components/approval-controls"
import {
  AssistantLiveActivityRow,
  MessageRow,
} from "@/features/conversations/components/message-row"
import type {
  AgentRun,
  AgentRunResumeDecision,
  ConversationMessage,
  PendingDelegatedApproval,
  PendingToolApproval,
} from "@/features/conversations/types"
import type {
  ApprovalState,
  ChatMessageDraft,
  ToolCallState,
} from "@/features/conversations/stream/reducer"
import {
  parseConversationMessages,
  delegationDetailsForToolActivity,
  delegationDetailsForPendingApproval,
  mergeDelegationDetails,
  normalizeToolArgs,
  pendingMessagesForConversation,
  type PendingUserMessage,
  type ToolActivity,
} from "@/features/conversations/message-parts"

type MessageListProps = {
  conversationId: string
  messages: ConversationMessage[]
  activeRun: AgentRun | null
  approvalError: string | null
  approvals: PendingToolApproval[]
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
  const visiblePendingUserMessages = pendingMessagesForConversation(
    pendingUserMessages,
    conversationId,
    messages,
    streamConversationId
  )
  const shouldShowStream = streamConversationId === conversationId
  const liveToolActivities = useMemo(
    () => buildLiveToolActivities(streamToolCalls, streamApprovals),
    [streamToolCalls, streamApprovals]
  )
  const approvalIds = useMemo(
    () => new Set(approvals.map((approval) => approval.tool_call_id)),
    [approvals]
  )
  const visibleLiveToolActivities = useMemo(
    () =>
      liveToolActivities.filter(
        (activity) => !(approvalIds.has(activity.id) && activity.status === "awaiting_approval")
      ),
    [approvalIds, liveToolActivities]
  )
  const hasInlineApprovals = approvals.length > 0 || isApprovalLoading || Boolean(approvalError)
  const hasMessages =
    parsedMessages.length > 0 ||
    visiblePendingUserMessages.length > 0 ||
    hasInlineApprovals ||
    (shouldShowStream &&
      (isStreaming || streamMessages.length > 0 || visibleLiveToolActivities.length > 0))

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
    <div className="flex min-w-0 flex-col gap-6">
      {parsedMessages.map((message) => (
        <MessageRow key={message.id} assistantLabel={assistantLabel} message={message} />
      ))}

      {visiblePendingUserMessages.map((message) => (
        <MessageRow key={message.clientMessageId} pendingMessage={message} />
      ))}

      {shouldShowStream &&
        (isStreaming || streamMessages.length > 0 || visibleLiveToolActivities.length > 0) && (
          <AssistantLiveActivityRow
            assistantLabel={assistantLabel}
            isStreaming={isStreaming}
            messages={streamMessages}
            toolActivities={visibleLiveToolActivities}
          />
        )}

      {hasInlineApprovals && (
        <ApprovalControls
          approvals={approvals}
          assistantLabel={assistantLabel}
          error={approvalError}
          isLoading={isApprovalLoading}
          isSubmitting={isApprovalSubmitting}
          onSubmit={onApprovalSubmit}
        />
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
  )
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
