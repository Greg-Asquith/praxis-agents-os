// apps/web/src/features/conversations/conversation-workspace-context.ts

import { createContext, use } from "react"

import type { Conversation, ConversationMessage } from "@/features/conversations/types"
import type { PendingUserMessage } from "@/features/conversations/message-parts"
import type { useAgentStream } from "@/features/conversations/stream/use-agent-stream"

type AgentStreamControls = ReturnType<typeof useAgentStream>

export type ConversationWorkspaceContextValue = {
  conversations: Conversation[]
  pendingUserMessages: PendingUserMessage[]
  addPendingUserMessage: (message: PendingUserMessage) => void
  removePendingUserMessage: (clientMessageId: string) => void
  clearPersistedPendingMessages: (messages: ConversationMessage[]) => void
  stream: AgentStreamControls
}

export const ConversationWorkspaceContext = createContext<ConversationWorkspaceContextValue | null>(
  null
)

export function useConversationWorkspace() {
  const value = use(ConversationWorkspaceContext)
  if (value === null) {
    throw new Error("Conversation workspace context is missing.")
  }
  return value
}
