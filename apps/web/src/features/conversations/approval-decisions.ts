// apps/web/src/features/conversations/approval-decisions.ts

import type { ApprovalDecision } from "@/components/tool-ui/approval-card"
import type { AgentRunResumeDecision, PendingToolApproval } from "@/features/conversations/types"
import { normalizeToolArgs } from "@/features/conversations/message-parts"
import { normalizeOptionalText } from "@/lib/format"
import { isRecord } from "@/lib/guards"

export type ApprovalDecisionMap = Record<string, ApprovalDecision>

export type ApprovalDecisionSummary = {
  allDecided: boolean
  approved: number
  denied: number
  pending: number
}

export const DEFAULT_APPROVAL_DECISION: ApprovalDecision = {
  decision: "pending",
  message: "",
  edits: {},
}

export function shouldSubmitDecisions(
  previous: ApprovalDecision,
  next: ApprovalDecision,
  summary: ApprovalDecisionSummary
): boolean {
  const isNewDecision = previous.decision === "pending" && next.decision !== "pending"
  return isNewDecision && summary.allDecided
}

export function buildResumeDecisions(
  approvals: PendingToolApproval[],
  decisions: ApprovalDecisionMap
): AgentRunResumeDecision[] | string {
  const payload: AgentRunResumeDecision[] = []

  for (const approval of approvals) {
    const decision = decisions[approval.tool_call_id]
    const effectiveDecision = decision ?? DEFAULT_APPROVAL_DECISION

    if (effectiveDecision.decision === "pending") {
      return "Choose approve or decline for every tool request."
    }

    if (effectiveDecision.decision === "denied") {
      payload.push({
        decision: "denied",
        message: normalizeOptionalText(effectiveDecision.message),
        tool_call_id: approval.tool_call_id,
      })
      continue
    }

    const mergedArgs = buildMergedArgs(approval.args, effectiveDecision.edits)
    if (typeof mergedArgs === "string") {
      return mergedArgs
    }

    payload.push({
      decision: "approved",
      override_args: mergedArgs,
      tool_call_id: approval.tool_call_id,
    })
  }

  return payload
}

export function summarizeApprovalDecisions(
  approvals: PendingToolApproval[],
  decisions: ApprovalDecisionMap
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

function buildMergedArgs(
  original: unknown,
  edits: Record<string, string>
): Record<string, unknown> | null | string {
  const editEntries = Object.entries(edits)
  if (editEntries.length === 0) {
    return null
  }

  const originalArgs = normalizeToolArgs(original)
  if (!isRecord(originalArgs)) {
    return "This request can no longer be edited. Refresh and try again."
  }

  const changedEntries: [string, string][] = []
  for (const [key, edit] of editEntries) {
    const originalValue = originalArgs[key]
    if (typeof originalValue !== "string") {
      return "This request can no longer be edited. Refresh and try again."
    }

    const trimmedEdit = edit.trim()
    const trimmedOriginal = originalValue.trim()
    if (trimmedEdit === trimmedOriginal || (!trimmedEdit && trimmedOriginal)) {
      continue
    }
    changedEntries.push([key, trimmedEdit])
  }

  return changedEntries.length > 0
    ? { ...originalArgs, ...Object.fromEntries(changedEntries) }
    : null
}
