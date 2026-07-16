import { describe, expect, it } from "vitest"

import { pendingMessagesForConversation } from "@/features/conversations/message-parts"
import type { PendingUserMessage } from "@/features/conversations/message-parts"
import type { ConversationMessage } from "@/features/conversations/types"

describe("pending conversation messages", () => {
  it("hands a pending message off when the persisted copy appears", () => {
    const pending = [pendingMessage("client-1", "conversation-1")]
    const persisted = [{ client_message_id: "client-1" }] as ConversationMessage[]

    expect(pendingMessagesForConversation(pending, "conversation-1", persisted)).toEqual([])
  })

  it("shows a new-conversation message through its assigned conversation alias", () => {
    const pending = [pendingMessage("client-2", null)]

    expect(pendingMessagesForConversation(pending, "conversation-2", [], "conversation-2")).toEqual(
      pending
    )
  })
})

function pendingMessage(
  clientMessageId: string,
  conversationId: string | null
): PendingUserMessage {
  return {
    attachments: [],
    clientMessageId,
    conversationId,
    createdAt: "2026-07-16T12:00:00Z",
    text: "Hello",
  }
}
