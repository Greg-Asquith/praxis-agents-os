// apps/web/src/features/conversations/conversation-heal-polling.ts

import { isRunStatusPolling } from "@/features/conversations/message-parts"
import type { AgentRunStatus } from "@/features/conversations/types"
import type { ConversationActiveRunResponse } from "@/features/conversations/types"

export const CONVERSATION_HEAL_POLL_INTERVAL_MS = 4_000
export const APPROVAL_EXPIRY_HEAL_POLL_INTERVAL_MS = 5_000
const MAX_TIMER_DELAY_MS = 2_147_000_000

export function conversationHealPollInterval(
  status: AgentRunStatus | null | undefined,
  error: unknown,
  streamConnected: boolean
) {
  return error === null && !streamConnected && isRunStatusPolling(status)
    ? CONVERSATION_HEAL_POLL_INTERVAL_MS
    : false
}

export function conversationActiveRunRefetchInterval(
  response: ConversationActiveRunResponse | undefined,
  error: unknown,
  streamConnected: boolean,
  nowMs = Date.now()
) {
  const activeInterval = conversationHealPollInterval(
    response?.active_run?.status,
    error,
    streamConnected
  )
  if (activeInterval !== false || error !== null) {
    return activeInterval
  }
  if (response?.active_run?.status !== "awaiting_approval") {
    return false
  }

  const expiresAtMs = Date.parse(response.approval_expires_at ?? "")
  if (!Number.isFinite(expiresAtMs)) {
    return false
  }
  const delayMs = expiresAtMs - nowMs
  if (delayMs <= 0) {
    return APPROVAL_EXPIRY_HEAL_POLL_INTERVAL_MS
  }
  return Math.min(delayMs + APPROVAL_EXPIRY_HEAL_POLL_INTERVAL_MS, MAX_TIMER_DELAY_MS)
}
