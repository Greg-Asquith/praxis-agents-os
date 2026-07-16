// apps/web/src/features/conversations/conversation-heal-polling.ts

import { isRunStatusPolling } from "@/features/conversations/message-parts"
import type { AgentRunStatus } from "@/features/conversations/types"

export const CONVERSATION_HEAL_POLL_INTERVAL_MS = 1_000

export function conversationHealPollInterval(
  status: AgentRunStatus | null | undefined,
  error: unknown
) {
  return error === null && isRunStatusPolling(status) ? CONVERSATION_HEAL_POLL_INTERVAL_MS : false
}
