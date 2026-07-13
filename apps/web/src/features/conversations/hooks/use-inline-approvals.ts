// apps/web/src/features/conversations/hooks/use-inline-approvals.ts

import { useMemo, useState } from "react"

import type { ApprovalDecisionResolver } from "@/features/conversations/approval-decision-context"
import {
  buildResumeDecisions,
  DEFAULT_APPROVAL_DECISION,
  shouldAutoSubmitDecisions,
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
  const approvalsById = useMemo(
    () => new Map(approvals.map((approval) => [approval.tool_call_id, approval])),
    [approvals]
  )
  const summary = summarizeApprovalDecisions(approvals, decisions)

  async function submit(decisionMap: LocalApprovalDecisionMap) {
    const payload = buildResumeDecisions(approvals, decisionMap)
    if (typeof payload === "string") {
      setFormError(payload)
      return
    }

    try {
      await onSubmit(payload)
      setDecisions({})
    } catch (submitError) {
      setFormError(submitError instanceof Error ? submitError.message : "Approval submit failed.")
    }
  }

  function handleDecisionChange(toolCallId: string, next: LocalApprovalDecision) {
    setFormError(null)
    const previous = decisions[toolCallId] ?? DEFAULT_APPROVAL_DECISION
    const nextDecisions = { ...decisions, [toolCallId]: next }
    setDecisions(nextDecisions)

    // Approving the last undecided request resumes the run immediately; staged
    // denials wait for the explicit send so the user can add an optional message.
    if (
      shouldAutoSubmitDecisions(
        previous,
        next,
        summarizeApprovalDecisions(approvals, nextDecisions)
      )
    ) {
      void submit(nextDecisions)
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
      disabled: isSubmitting,
      onDecisionChange: (next) => {
        handleDecisionChange(activity.id, next)
      },
    }
  }

  return {
    formError,
    resolveApprovalControls,
    submitStaged: () => {
      void submit(decisions)
    },
    summary,
  }
}
