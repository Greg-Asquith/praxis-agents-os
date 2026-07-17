// apps/web/src/features/conversations/hooks/use-inline-approvals.ts

import { useMemo, useRef, useState } from "react"

import type { ApprovalDecisionResolver } from "@/features/conversations/approval-decision-context"
import {
  buildResumeDecisions,
  DEFAULT_APPROVAL_DECISION,
  shouldSubmitDecisions,
  summarizeApprovalDecisions,
  type LocalApprovalDecision,
  type LocalApprovalDecisionMap,
} from "@/features/conversations/approval-decisions"
import type { AgentRunResumeDecision, PendingToolApproval } from "@/features/conversations/types"

type UseInlineApprovalsParams = {
  approvals: PendingToolApproval[]
  enabled: boolean
  isSubmitting: boolean
  onSubmit: (decisions: AgentRunResumeDecision[]) => Promise<void>
}

export function useInlineApprovals({
  approvals,
  enabled,
  isSubmitting,
  onSubmit,
}: UseInlineApprovalsParams) {
  const [decisions, setDecisions] = useState<LocalApprovalDecisionMap>({})
  const [formError, setFormError] = useState<string | null>(null)
  const [formErrorToolCallId, setFormErrorToolCallId] = useState<string | null>(null)
  const [submittingToolCallId, setSubmittingToolCallId] = useState<string | null>(null)
  const submissionInFlight = useRef(false)
  const approvalsById = useMemo(
    () => new Map(approvals.map((approval) => [approval.tool_call_id, approval])),
    [approvals]
  )
  const summary = summarizeApprovalDecisions(approvals, decisions)

  async function submit(decisionMap: LocalApprovalDecisionMap, toolCallId: string) {
    if (submissionInFlight.current) {
      return
    }
    setFormError(null)
    setFormErrorToolCallId(null)
    const payload = buildResumeDecisions(approvals, decisionMap)
    if (typeof payload === "string") {
      setFormError(payload)
      setFormErrorToolCallId(toolCallId)
      return
    }

    submissionInFlight.current = true
    setSubmittingToolCallId(toolCallId)
    try {
      await onSubmit(payload)
      setDecisions({})
    } catch (submitError) {
      setFormError(submitError instanceof Error ? submitError.message : "Approval submit failed.")
      setFormErrorToolCallId(toolCallId)
    } finally {
      submissionInFlight.current = false
      setSubmittingToolCallId(null)
    }
  }

  function handleDecisionChange(toolCallId: string, next: LocalApprovalDecision) {
    setFormError(null)
    const previous = decisions[toolCallId] ?? DEFAULT_APPROVAL_DECISION
    const nextDecisions = { ...decisions, [toolCallId]: next }
    setDecisions(nextDecisions)

    if (
      shouldSubmitDecisions(previous, next, summarizeApprovalDecisions(approvals, nextDecisions))
    ) {
      void submit(nextDecisions, toolCallId)
    }
  }

  const resolveApprovalControls: ApprovalDecisionResolver = (activity) => {
    if (!enabled || activity.status !== "awaiting_approval") {
      return null
    }
    if (!approvalsById.has(activity.id)) {
      return null
    }

    return {
      decision: decisions[activity.id] ?? DEFAULT_APPROVAL_DECISION,
      disabled: isSubmitting || submittingToolCallId !== null,
      error: formErrorToolCallId === activity.id ? formError : null,
      pendingCount: summary.pending,
      submitting: submittingToolCallId === activity.id,
      onDecisionChange: (next) => {
        handleDecisionChange(activity.id, next)
      },
      onRetry: () => {
        void submit(decisions, activity.id)
      },
    }
  }

  return {
    resolveApprovalControls,
  }
}
