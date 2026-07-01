// apps/web/src/features/conversations/components/message-list.tsx

import { useMemo } from "react"
import { CircleDashedIcon, MessageSquareTextIcon } from "lucide-react"

import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert"
import { AssistantDraftRow, MessageRow } from "@/features/conversations/components/message-row"
import { ToolCallRow } from "@/features/conversations/components/tool-call-row"
import type { AgentRun, ConversationMessage } from "@/features/conversations/types"
import type {
  ApprovalState,
  ChatMessageDraft,
  ToolCallState,
} from "@/features/conversations/stream/reducer"
import {
  parseConversationMessages,
  pendingMessagesForConversation,
  type PendingUserMessage,
  type ToolActivity,
} from "@/features/conversations/message-parts"

type MessageListProps = {
  conversationId: string
  messages: ConversationMessage[]
  activeRun: AgentRun | null
  pendingUserMessages: PendingUserMessage[]
  streamMessages: ChatMessageDraft[]
  streamToolCalls: ToolCallState[]
  streamApprovals: ApprovalState[]
  streamError?: string | null
  streamConversationId: string | null
  isStreaming: boolean
}

export function MessageList({
  conversationId,
  messages,
  activeRun,
  pendingUserMessages,
  streamMessages,
  streamToolCalls,
  streamApprovals,
  streamError,
  streamConversationId,
  isStreaming,
}: MessageListProps) {
  const parsedMessages = useMemo(
    () => parseConversationMessages(messages, activeRun?.status),
    [messages, activeRun?.status]
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
  const hasMessages =
    parsedMessages.length > 0 ||
    visiblePendingUserMessages.length > 0 ||
    (shouldShowStream && (streamMessages.length > 0 || liveToolActivities.length > 0))

  if (!hasMessages) {
    return (
      <div className="flex min-h-80 flex-col items-center justify-center rounded-xl border border-dashed p-8 text-center">
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
    <div className="flex min-w-0 flex-col gap-1">
      {parsedMessages.map((message) => (
        <MessageRow key={message.id} message={message} />
      ))}

      {visiblePendingUserMessages.map((message) => (
        <MessageRow key={message.clientMessageId} pendingMessage={message} />
      ))}

      {shouldShowStream &&
        streamMessages.map((message) => (
          <AssistantDraftRow
            key={message.id}
            id={message.id}
            text={message.text}
            streaming={message.status === "streaming"}
          />
        ))}

      {shouldShowStream && liveToolActivities.length > 0 && (
        <div className="mx-auto flex w-full max-w-3xl flex-col gap-2 px-1 py-1">
          {liveToolActivities.map((activity) => (
            <ToolCallRow key={`${activity.id}:${activity.kind}`} activity={activity} />
          ))}
        </div>
      )}

      {shouldShowStream && isStreaming && streamMessages.length === 0 && (
        <div className="mx-auto flex w-full max-w-3xl items-center gap-2 px-1 py-3 text-sm">
          <CircleDashedIcon className="text-muted-foreground size-4 animate-spin" />
          <span className="text-muted-foreground">Agent is working</span>
        </div>
      )}

      {streamError && (
        <div className="mx-auto w-full max-w-3xl px-1 py-2">
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
  const activities = toolCalls.map((toolCall): ToolActivity => ({
    id: toolCall.tool_call_id,
    kind: toolCall.status === "awaiting_approval" ? "approval" : "call",
    status: toolCall.status,
    name: toolCall.name,
    args: toolCall.args,
    result: toolCall.result,
  }))

  for (const approval of approvals) {
    if (activities.some((activity) => activity.id === approval.tool_call_id)) {
      continue
    }

    activities.push({
      id: approval.tool_call_id,
      kind: "approval",
      status: "awaiting_approval",
      name: approval.name,
      args: approval.args,
    })
  }

  return activities
}
