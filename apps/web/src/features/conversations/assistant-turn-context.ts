// apps/web/src/features/conversations/assistant-turn-context.ts

import { createContext } from "react"

export type AssistantTurnIdentity = {
  agentId: string
  label: string
  metadata: Record<string, unknown> | null | undefined
}

// Lets tool rows inside an assistant turn name the agent that produced it.
export const AssistantTurnContext = createContext<AssistantTurnIdentity | null>(null)
