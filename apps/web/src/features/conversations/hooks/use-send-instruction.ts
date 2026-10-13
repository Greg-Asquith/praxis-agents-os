// apps/web/src/features/conversations/hooks/use-send-instruction.ts

import { useCallback } from "react"

import type { SendInstruction } from "@/features/conversations/conversation-actions-context"
import { useConversationWorkspace } from "@/features/conversations/conversation-workspace-context"

export function useSendInstruction(
  conversationId: string,
  disabled: boolean
): SendInstruction | null {
  const { addPendingUserMessage, removePendingUserMessage, stream } = useConversationWorkspace()
  const { sendTurn } = stream
  const send = useCallback(
    async (text: string) => {
      const clientMessageId = globalThis.crypto.randomUUID()
      addPendingUserMessage({
        attachments: [],
        clientMessageId,
        conversationId,
        createdAt: new Date().toISOString(),
        text,
      })
      try {
        await sendTurn({
          conversationId,
          payload: { attachments: [], client_message_id: clientMessageId, user_prompt: text },
        })
      } finally {
        removePendingUserMessage(clientMessageId)
      }
    },
    [addPendingUserMessage, conversationId, removePendingUserMessage, sendTurn]
  )
  const busy = stream.isStreaming && stream.conversationId === conversationId
  return disabled || busy ? null : send
}
