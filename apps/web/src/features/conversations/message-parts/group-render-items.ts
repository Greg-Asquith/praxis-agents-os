// apps/web/src/features/conversations/message-parts/group-render-items.ts

import type {
  ParsedConversationMessage,
  ToolActivity,
} from "@/features/conversations/message-parts/types"

export type ConversationRenderItem =
  | {
      kind: "message"
      id: string
      message: ParsedConversationMessage
    }
  | {
      kind: "assistant-turn"
      id: string
      agentRunId: string
      createdAt: string
      messages: ParsedConversationMessage[]
      toolActivities: ToolActivity[]
    }

type AssistantTurnAccumulator = {
  agentRunId: string
  firstMessageId: string
  createdAt: string
  messages: ParsedConversationMessage[]
  toolActivities: ToolActivity[]
}

type AssistantTurnMessage = ParsedConversationMessage & { agentRunId: string }

export function groupConversationRenderItems(
  messages: ParsedConversationMessage[]
): ConversationRenderItem[] {
  const items: ConversationRenderItem[] = []
  let pendingTurn: AssistantTurnAccumulator | null = null

  for (const message of messages) {
    if (!belongsToAssistantTurn(message)) {
      if (pendingTurn !== null) {
        items.push(assistantTurnItem(pendingTurn))
        pendingTurn = null
      }
      items.push({ kind: "message", id: message.id, message })
      continue
    }

    if (pendingTurn !== null && pendingTurn.agentRunId === message.agentRunId) {
      appendMessageToTurn(pendingTurn, message)
      continue
    }

    if (pendingTurn !== null) {
      items.push(assistantTurnItem(pendingTurn))
    }
    pendingTurn = createAssistantTurn(message)
  }

  if (pendingTurn !== null) {
    items.push(assistantTurnItem(pendingTurn))
  }

  return items
}

function belongsToAssistantTurn(
  message: ParsedConversationMessage
): message is AssistantTurnMessage {
  return message.agentRunId !== null && message.role !== "user"
}

function createAssistantTurn(message: AssistantTurnMessage): AssistantTurnAccumulator {
  return {
    agentRunId: message.agentRunId,
    firstMessageId: message.id,
    createdAt: message.createdAt,
    messages: [message],
    toolActivities: [...message.toolActivities],
  }
}

function appendMessageToTurn(turn: AssistantTurnAccumulator, message: ParsedConversationMessage) {
  turn.messages.push(message)
  turn.toolActivities.push(...message.toolActivities)
}

function assistantTurnItem(turn: AssistantTurnAccumulator): ConversationRenderItem {
  return {
    kind: "assistant-turn",
    id: `assistant-turn:${turn.agentRunId}:${turn.firstMessageId}`,
    agentRunId: turn.agentRunId,
    createdAt: turn.createdAt,
    messages: turn.messages,
    toolActivities: turn.toolActivities,
  }
}
