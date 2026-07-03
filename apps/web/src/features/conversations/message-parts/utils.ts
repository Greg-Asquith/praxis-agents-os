// apps/web/src/features/conversations/message-parts/utils.ts

import type { AgentRunStatus } from "@/features/conversations/types"

const PREVIEW_LIMIT = 2400

export function isRunStatusPolling(status: AgentRunStatus | null | undefined) {
  return status === "pending" || status === "running"
}

export function normalizeToolArgs(value: unknown) {
  if (typeof value !== "string") {
    return value
  }

  try {
    return JSON.parse(value) as unknown
  } catch {
    return value
  }
}

export function safeJsonPreview(value: unknown, limit = PREVIEW_LIMIT) {
  let raw: string
  try {
    raw = JSON.stringify(value, null, 2)
  } catch {
    raw = String(value)
  }

  if (raw.length <= limit) {
    return raw
  }

  return `${raw.slice(0, limit)}\n...`
}
