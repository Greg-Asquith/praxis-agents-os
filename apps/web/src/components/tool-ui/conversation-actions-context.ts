// apps/web/src/components/tool-ui/conversation-actions-context.ts

import { createContext, use, useState } from "react"

import { getErrorMessage } from "@/lib/api/errors"

// Sends text as the person's own governed turn; null while the conversation can't take one.
export type SendInstruction = (text: string) => Promise<void>

export const ConversationActionsContext = createContext<SendInstruction | null>(null)

/** Sends a card's instruction as a governed turn; `send` resolves true once the turn is accepted. */
export function useInstructionAction() {
  const sendInstruction = use(ConversationActionsContext)
  const [sending, setSending] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function send(text: string): Promise<boolean> {
    if (!sendInstruction) return false
    setError(null)
    setSending(true)
    try {
      await sendInstruction(text)
      return true
    } catch (sendError) {
      setError(getErrorMessage(sendError))
      return false
    } finally {
      setSending(false)
    }
  }

  return { available: sendInstruction !== null, error, send, sending }
}
