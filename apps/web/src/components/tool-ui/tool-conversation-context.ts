// apps/web/src/components/tool-ui/tool-conversation-context.ts

import { createContext } from "react"

export const ToolConversationContext = createContext<string | null>(null)
export const SharedTranscriptContext = createContext(false)
