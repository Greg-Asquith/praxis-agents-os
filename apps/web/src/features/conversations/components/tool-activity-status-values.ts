// apps/web/src/features/conversations/components/tool-activity-status-values.ts

import type { DelegationToolActivity, ToolActivity } from "@/features/conversations/message-parts"

type DelegationStatus = DelegationToolActivity["status"]

const TOOL_VERBS: Partial<Record<ToolActivity["status"], string>> = {
  awaiting_approval: "Requested",
  denied: "Declined",
  running: "Running",
}

const DELEGATION_VERBS: Partial<Record<DelegationStatus, string>> = {
  failed: "Delegation failed for",
  running: "Delegating to",
}

const TOOL_SUFFIXES: Partial<Record<ToolActivity["status"], string>> = {
  awaiting_approval: "· Waiting",
  denied: "· Declined",
  failed: "· Failed",
}

const DELEGATION_SUFFIXES: Partial<Record<DelegationStatus, string>> = {
  awaiting_approval: "· Waiting",
  failed: "· Failed",
  unknown: "· Unknown",
}

export function toolActivityVerb(activity: ToolActivity) {
  return TOOL_VERBS[activity.status] ?? "Ran"
}

export function toolStatusSuffix(activity: ToolActivity) {
  return TOOL_SUFFIXES[activity.status] ?? decisionSuffix(activity) ?? null
}

export function delegationActivityVerb(status: DelegationStatus) {
  return DELEGATION_VERBS[status] ?? "Delegated to"
}

export function delegationStatusSuffix(status: DelegationStatus) {
  return DELEGATION_SUFFIXES[status] ?? null
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
