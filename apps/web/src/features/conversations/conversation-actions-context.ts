// apps/web/src/features/conversations/conversation-actions-context.ts

import { createContext } from "react"

import type { ToolRowActions } from "@/integrations/contract"

// Tool rows surface first-class actions (for example "Reply") that start a
// governed agent turn; the conversation route provides the live dispatcher.
export const ConversationActionsContext = createContext<ToolRowActions>({
  sendInstruction: null,
})
