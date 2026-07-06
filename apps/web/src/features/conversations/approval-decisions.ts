// apps/web/src/features/conversations/approval-decisions.ts

import type { AgentRunResumeDecision, PendingToolApproval } from "@/features/conversations/types"
import { normalizeOptionalText } from "@/lib/format"

export type LocalApprovalDecision =
  | { decision: "pending"; message: ""; overrideArgs: "" }
  | { decision: "approved"; message: ""; overrideArgs: string }
  | { decision: "denied"; message: string; overrideArgs: "" }

export type LocalApprovalDecisionMap = Record<string, LocalApprovalDecision>

export type ApprovalDecisionSummary = {
  allDecided: boolean
  approved: number
  denied: number
  pending: number
}

export const DEFAULT_APPROVAL_DECISION: LocalApprovalDecision = {
  decision: "pending",
  message: "",
  overrideArgs: "",
}

export function approveDecision(decision: LocalApprovalDecision): LocalApprovalDecision {
  return {
    decision: "approved",
    message: "",
    overrideArgs: decision.decision === "approved" ? decision.overrideArgs : "",
  }
}

export function denyDecision(decision: LocalApprovalDecision): LocalApprovalDecision {
  return {
    decision: "denied",
    message: decision.decision === "denied" ? decision.message : "",
    overrideArgs: "",
  }
}

export function buildResumeDecisions(
  approvals: PendingToolApproval[],
  decisions: LocalApprovalDecisionMap
): AgentRunResumeDecision[] | string {
  const payload: AgentRunResumeDecision[] = []

  for (const approval of approvals) {
    const decision = decisions[approval.tool_call_id]
    const effectiveDecision = decision ?? DEFAULT_APPROVAL_DECISION

    if (effectiveDecision.decision === "pending") {
      return "Choose approve or deny for every tool request."
    }

    if (effectiveDecision.decision === "denied") {
      payload.push({
        decision: "denied",
        message: normalizeOptionalText(effectiveDecision.message),
        tool_call_id: approval.tool_call_id,
      })
      continue
    }

    const overrideArgs = parseOverrideArgs(effectiveDecision.overrideArgs)
    if (typeof overrideArgs === "string") {
      return overrideArgs
    }

    payload.push({
      decision: "approved",
      override_args: overrideArgs,
      tool_call_id: approval.tool_call_id,
    })
  }

  return payload
}

export function summarizeApprovalDecisions(
  approvals: PendingToolApproval[],
  decisions: LocalApprovalDecisionMap
): ApprovalDecisionSummary {
  let pending = 0
  let approved = 0
  let denied = 0

  for (const approval of approvals) {
    const decision = decisions[approval.tool_call_id] ?? DEFAULT_APPROVAL_DECISION
    if (decision.decision === "approved") {
      approved += 1
    } else if (decision.decision === "denied") {
      denied += 1
    } else {
      pending += 1
    }
  }

  return {
    allDecided: approvals.length > 0 && pending === 0,
    approved,
    denied,
    pending,
  }
}

function parseOverrideArgs(value: string): Record<string, unknown> | null | string {
  const trimmed = value.trim()
  if (!trimmed) {
    return null
  }

  try {
    const parsed = JSON.parse(trimmed) as unknown
    if (typeof parsed !== "object" || parsed === null || Array.isArray(parsed)) {
      return "Override args must be a JSON object."
    }
    return parsed as Record<string, unknown>
  } catch {
    return "Override args must be valid JSON."
  }
}
