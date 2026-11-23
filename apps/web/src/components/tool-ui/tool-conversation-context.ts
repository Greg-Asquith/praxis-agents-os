// apps/web/src/components/tool-ui/tool-conversation-context.ts

import { createContext, use } from "react"

export const ToolConversationContext = createContext<string | null>(null)
export const SharedTranscriptContext = createContext(false)

/** The conversation a card can act in, or null on shared transcripts and outside chats. */
export function useActionableConversation(): string | null {
  const conversationId = use(ToolConversationContext)
  const shared = use(SharedTranscriptContext)
  return shared ? null : conversationId
}
