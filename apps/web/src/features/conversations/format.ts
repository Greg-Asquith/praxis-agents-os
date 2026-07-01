// apps/web/src/features/conversations/format.ts

import type { AgentRunStatus, Conversation } from "@/features/conversations/types"
import { titleCaseToken } from "@/lib/format"

const SOURCE_LABELS: Record<string, string> = {
  delegated: "Delegated",
  direct: "Direct",
  scheduled: "Scheduled",
}

const RUN_STATUS_LABELS: Record<AgentRunStatus, string> = {
  awaiting_approval: "Waiting for approval",
  cancelled: "Cancelled",
  completed: "Completed",
  failed: "Failed",
  pending: "Pending",
  running: "Running",
}

export function conversationAgentLabel(conversation: Conversation, fallbackLabel = "No agent") {
  const agentName = conversation.agent_name?.trim()
  if (agentName) {
    return agentName
  }

  if (conversation.agent_slug || conversation.active_agent_id) {
    return "Assigned agent"
  }

  return fallbackLabel
}

export function sourceLabel(source: string) {
  return SOURCE_LABELS[source] ?? titleCaseToken(source, "Unknown")
}

export function runStatusLabel(status: AgentRunStatus) {
  return RUN_STATUS_LABELS[status]
}

export function supportIdentifier(value: string | null | undefined) {
  const trimmed = value?.trim()
  if (!trimmed) {
    return null
  }

  return trimmed.length > 12 ? trimmed.slice(0, 8) : trimmed
}
