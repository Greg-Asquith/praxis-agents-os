// apps/web/src/features/conversations/conversation-heal-polling.ts

import { CancelledError } from "@tanstack/react-query"

import { ApiError } from "@/lib/api/errors"
import { isRunStatusPolling } from "@/features/conversations/message-parts"
import type { AgentRunStatus } from "@/features/conversations/types"
import type { ConversationActiveRunResponse } from "@/features/conversations/types"

export const CONVERSATION_HEAL_POLL_INTERVAL_MS = 4_000
export const APPROVAL_EXPIRY_HEAL_POLL_INTERVAL_MS = 5_000
const MAX_TIMER_DELAY_MS = 2_147_000_000

export function conversationHealPollInterval(
  status: AgentRunStatus | null | undefined,
  error: unknown,
  streamConnected: boolean,
  failureCount = 1
) {
  if (streamConnected) return false
  if (error !== null) return conversationRecoveryDelay(error, failureCount)
  return isRunStatusPolling(status) ? CONVERSATION_HEAL_POLL_INTERVAL_MS : false
}

export function conversationActiveRunRefetchInterval(
  response: ConversationActiveRunResponse | undefined,
  error: unknown,
  streamConnected: boolean,
  nowMs = Date.now(),
  failureCount = 1
) {
  const activeInterval = conversationHealPollInterval(
    response?.active_run?.status,
    error,
    streamConnected,
    failureCount
  )
  if (streamConnected || activeInterval !== false || error !== null) {
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

export class ConversationProjectionChangedError extends Error {
  constructor() {
    super("The approval requests changed while refreshing.")
    this.name = "ConversationProjectionChangedError"
  }
}

export function isConversationReadRecoverable(error: unknown) {
  if (error instanceof CancelledError || (error instanceof Error && error.name === "AbortError")) {
    return false
  }
  if (error instanceof ApiError) return error.status === 429 || error.status >= 500
  return error instanceof TypeError || error instanceof ConversationProjectionChangedError
}

export function conversationReadRetry(failureCount: number, error: unknown) {
  return failureCount < 2 && isConversationReadRecoverable(error)
}

function conversationRecoveryDelay(error: unknown, failureCount = 1) {
  return isConversationReadRecoverable(error)
    ? Math.min(4_000 * 2 ** Math.min(Math.max(failureCount - 1, 0), 3), 30_000)
    : false
}

export function createConversationRecoveryCounter() {
  let baseline = 0
  let successTime = 0
  return (state: { errorUpdateCount: number; dataUpdatedAt: number }) => {
    if (state.dataUpdatedAt !== successTime) {
      baseline = state.errorUpdateCount
      successTime = state.dataUpdatedAt
    }
    return Math.max(1, state.errorUpdateCount - baseline)
  }
}

export function conversationRecoveryMessage(error: unknown) {
  if (error instanceof ApiError) {
    if (error.status === 401) return "Your session has ended. Sign in again to continue."
    if (error.status === 403) return "You no longer have access to this conversation."
    if (error.status === 404) return "This conversation or run is no longer available."
  }
  if (isConversationReadRecoverable(error)) {
    return "Connection interrupted. Retrying to load the latest conversation."
  }
  return "The conversation could not be refreshed. Retry to load the latest state."
}
