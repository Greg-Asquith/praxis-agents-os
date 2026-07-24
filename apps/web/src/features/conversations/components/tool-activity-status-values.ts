// apps/web/src/features/conversations/components/tool-activity-status-values.ts

import type { ToolActivity } from "@/features/conversations/message-parts"

const TOOL_VERBS: Partial<Record<ToolActivity["status"], string>> = {
  awaiting_approval: "Requested",
  denied: "Declined",
  running: "Running",
}

const TOOL_SUFFIXES: Partial<Record<ToolActivity["status"], string>> = {
  awaiting_approval: "· Waiting",
  denied: "· Declined",
  failed: "· Failed",
}

export function toolActivityVerb(activity: ToolActivity) {
  return TOOL_VERBS[activity.status] ?? "Ran"
}

export function toolStatusSuffix(activity: ToolActivity) {
  return TOOL_SUFFIXES[activity.status] ?? decisionSuffix(activity) ?? null
}

function decisionSuffix(activity: ToolActivity) {
  if (activity.decision === "approved") {
    return "· Approved"
  }
  if (activity.decision === "denied") {
    return "· Declined"
  }
  return null
}
