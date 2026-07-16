// apps/web/src/features/conversations/format.ts

import type { AgentRunStatus, Conversation } from "@/features/conversations/types"
import { isRecord } from "@/lib/guards"

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

export function runStatusLabel(status: AgentRunStatus) {
  return RUN_STATUS_LABELS[status]
}

export function conversationScheduleContext(metadata: Record<string, unknown> | null) {
  if (!isRecord(metadata)) {
    return null
  }

  const schedule = metadata["schedule"]
  if (!isRecord(schedule)) {
    return null
  }

  return {
    scheduleId: typeof schedule["schedule_id"] === "string" ? schedule["schedule_id"] : null,
    scheduledFor: typeof schedule["scheduled_for"] === "string" ? schedule["scheduled_for"] : null,
  }
}

export function supportIdentifier(value: string | null | undefined) {
  const trimmed = value?.trim()
  if (!trimmed) {
    return null
  }

  return trimmed.length > 12 ? trimmed.slice(0, 8) : trimmed
}
