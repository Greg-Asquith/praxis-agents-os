// apps/web/src/features/conversations/conversation-actions-context.ts

import { createContext } from "react"

// Sends text as the person's own governed turn; null while the conversation can't take one.
export type SendInstruction = (text: string) => Promise<void>

export const ConversationActionsContext = createContext<SendInstruction | null>(null)
