// apps/web/src/features/conversations/conversation-actions-context.ts

import { createContext } from "react"

// Sends text as the person's own turn in the open conversation, so the agent acts on it
// under its usual tool policies. Null while the conversation can't take a turn.
export type SendInstruction = (text: string) => Promise<void>

export const ConversationActionsContext = createContext<SendInstruction | null>(null)
