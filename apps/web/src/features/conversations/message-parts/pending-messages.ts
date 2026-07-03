// apps/web/src/features/conversations/message-parts/pending-messages.ts

import type { PendingUserMessage } from "@/features/conversations/message-parts/types"
import type { ConversationMessage } from "@/features/conversations/types"

export function persistedClientMessageIds(messages: ConversationMessage[]) {
  return new Set(
    messages
      .map((message) => message.client_message_id)
      .filter((value): value is string => typeof value === "string" && value.length > 0)
  )
}

export function pendingMessagesForConversation(
  pendingMessages: PendingUserMessage[],
  conversationId: string,
  persistedMessages: ConversationMessage[],
  pendingConversationIdAlias: string | null = null
): PendingUserMessage[] {
  const persistedClientIds = persistedClientMessageIds(persistedMessages)

  return pendingMessages.filter(
    (message) =>
      (message.conversationId === conversationId ||
        (message.conversationId === null && pendingConversationIdAlias === conversationId)) &&
      !persistedClientIds.has(message.clientMessageId)
  )
}
