// apps/web/src/features/conversations/message-parts/timeline.ts

import { shouldShowLiveActivity } from "@/features/conversations/live-activity-visibility"
import { buildLiveToolActivities } from "@/features/conversations/live-tool-activities"
import { groupConversationRenderItems } from "@/features/conversations/message-parts/group-render-items"
import { pendingMessagesForConversation } from "@/features/conversations/message-parts/pending-messages"
import {
  delegationDetailsForPendingApproval,
  delegationDetailsForToolActivity,
} from "@/features/conversations/message-parts/delegation"
import {
  parseConversationMessages,
  type LiveToolResult,
} from "@/features/conversations/message-parts/parse"
import type { ConversationRenderItem } from "@/features/conversations/message-parts/group-render-items"
import type { PendingUserMessage, ToolActivity } from "@/features/conversations/message-parts/types"
import {
  normalizeToolArgs,
  toolActivityIdentity,
} from "@/features/conversations/message-parts/utils"
import {
  selectLiveTimeline,
  type ApprovalState,
  type ChatMessageDraft,
  type ToolCallState,
} from "@/features/conversations/stream/reducer"
import type {
  AgentRun,
  ConversationMessage,
  PendingDelegatedApproval,
  PendingToolApproval,
  PendingWorkflowState,
} from "@/features/conversations/types"

export type AssistantLiveTimelinePart =
  { kind: "text"; message: ChatMessageDraft } | { kind: "tool"; activity: ToolActivity }

export type ConversationTimelineRow =
  ConversationRenderItem | { kind: "pending-message"; id: string; message: PendingUserMessage }

type ConversationTimelineStream = {
  approvals: ApprovalState[]
  conversationId: string | null
  isStreaming: boolean
  messages: ChatMessageDraft[]
  runId: string | null
  toolCalls: ToolCallState[]
}

export type ConversationTimelineInput = {
  approvals: PendingToolApproval[]
  assistantAgentId: string
  conversationId: string
  messages: ConversationMessage[]
  pendingDelegations: PendingDelegatedApproval[]
  pendingUserMessages: PendingUserMessage[]
  pendingWorkflow: PendingWorkflowState | null
  stream: ConversationTimelineStream
  transcriptRun: Pick<AgentRun, "id" | "status"> | null
}

export type ConversationTimeline = {
  approval: { requests: PendingToolApproval[]; runId: string } | null
  assistantAgentId: string
  liveActivity: {
    isStreaming: boolean
    messages: ChatMessageDraft[]
    timeline: AssistantLiveTimelinePart[]
  } | null
  orphanApprovals: ToolActivity[]
  rows: ConversationTimelineRow[]
  transcriptToolIds: ReadonlySet<string>
}

export function projectConversationTimeline({
  approvals,
  assistantAgentId,
  conversationId,
  messages,
  pendingDelegations,
  pendingUserMessages,
  pendingWorkflow,
  stream,
  transcriptRun,
}: ConversationTimelineInput): ConversationTimeline {
  const hasVisibleStream = stream.conversationId === conversationId
  const liveResultsByCallIdentity = new Map<string, LiveToolResult>()
  if (hasVisibleStream) {
    for (const toolCall of stream.toolCalls) {
      if (toolCall.status === "awaiting_approval") {
        continue
      }
      liveResultsByCallIdentity.set(toolActivityIdentity(stream.runId, toolCall.tool_call_id), {
        result: toolCall.result,
        status: toolCall.status,
      })
    }
  }

  const parsedMessages = parseConversationMessages(
    messages,
    transcriptRun,
    pendingDelegations,
    liveResultsByCallIdentity,
    pendingWorkflow
  )
  const transcriptToolIds = new Set(
    parsedMessages.flatMap((message) =>
      message.toolActivities.map((activity) =>
        toolActivityIdentity(activity.agentRunId, activity.id)
      )
    )
  )
  const liveToolActivities = buildLiveToolActivities(
    stream.toolCalls,
    stream.approvals,
    stream.runId
  )
  const activitiesByIdentity = new Map(
    liveToolActivities.map(
      (activity) => [toolActivityIdentity(activity.agentRunId, activity.id), activity] as const
    )
  )
  const liveTimeline = selectLiveTimeline(stream.messages, stream.toolCalls).flatMap(
    (item): AssistantLiveTimelinePart[] => {
      if (item.kind === "text") {
        return [{ kind: "text", message: item.message }]
      }
      const identity = toolActivityIdentity(stream.runId, item.toolCall.tool_call_id)
      if (transcriptToolIds.has(identity)) {
        return []
      }
      const activity = activitiesByIdentity.get(identity)
      return activity ? [{ kind: "tool", activity }] : []
    }
  )
  const hasRunningTranscriptTool = parsedMessages.some((message) =>
    message.toolActivities.some((activity) => activity.status === "running")
  )
  const showLiveActivity =
    hasVisibleStream &&
    shouldShowLiveActivity({
      hasRunningTranscriptTool,
      isStreaming: stream.isStreaming,
      liveMessageCount: stream.messages.length,
      liveToolActivityCount: liveToolActivities.length,
    })
  const approval =
    transcriptRun?.status === "awaiting_approval"
      ? { requests: approvals, runId: transcriptRun.id }
      : null
  const orphanApprovals = approval
    ? projectOrphanApprovals(parsedMessages, liveToolActivities, approval.requests, approval.runId)
    : []
  const visiblePendingUserMessages = pendingMessagesForConversation(
    pendingUserMessages,
    conversationId,
    messages,
    stream.conversationId
  )
  const rows: ConversationTimelineRow[] = [
    ...groupConversationRenderItems(parsedMessages),
    ...visiblePendingUserMessages.map((message) => ({
      id: `pending-message:${message.clientMessageId}`,
      kind: "pending-message" as const,
      message,
    })),
  ]

  return {
    approval,
    assistantAgentId,
    liveActivity: showLiveActivity
      ? {
          isStreaming: stream.isStreaming,
          messages: stream.messages,
          timeline: liveTimeline,
        }
      : null,
    orphanApprovals,
    rows,
    transcriptToolIds,
  }
}

function projectOrphanApprovals(
  parsedMessages: ReturnType<typeof parseConversationMessages>,
  liveToolActivities: ToolActivity[],
  approvals: PendingToolApproval[],
  runId: string
): ToolActivity[] {
  const renderedAwaitingIds = new Set(
    [...parsedMessages.flatMap((message) => message.toolActivities), ...liveToolActivities]
      .flatMap((activity) => [activity, ...(activity.script?.children ?? [])])
      .filter((activity) => activity.status === "awaiting_approval")
      .map((activity) => toolActivityIdentity(activity.agentRunId, activity.id))
  )
  return approvals
    .filter(
      (approval) => !renderedAwaitingIds.has(toolActivityIdentity(runId, approval.tool_call_id))
    )
    .map((approval) => orphanApprovalActivity(approval, runId))
}

function orphanApprovalActivity(approval: PendingToolApproval, agentRunId: string): ToolActivity {
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
