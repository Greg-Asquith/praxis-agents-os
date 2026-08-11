// apps/web/src/features/conversations/hooks/use-inline-approvals.ts

import { useMemo, useRef, useState } from "react"

import type { ApprovalDecision } from "@/components/tool-ui/approval-card"
import type { ApprovalDecisionResolver } from "@/features/conversations/approval-decision-context"
import {
  buildResumeDecisions,
  DEFAULT_APPROVAL_DECISION,
  shouldSubmitDecisions,
  summarizeApprovalDecisions,
  type ApprovalDecisionMap,
} from "@/features/conversations/approval-decisions"
import type { AgentRunResumeDecision, PendingToolApproval } from "@/features/conversations/types"
import type { ToolPresentationEntry } from "@/features/tools/types"

const NO_PRESENTATION = () => null

type UseInlineApprovalsParams = {
  activeRunId: string | null
  approvals: PendingToolApproval[]
  enabled: boolean
  isSubmitting: boolean
  onSubmit: (decisions: AgentRunResumeDecision[]) => Promise<void>
  presentationFor?: (name: string) => ToolPresentationEntry | null
}

export function useInlineApprovals({
  activeRunId,
  approvals,
  enabled,
  isSubmitting,
  onSubmit,
  presentationFor = NO_PRESENTATION,
}: UseInlineApprovalsParams) {
  const [decisions, setDecisions] = useState<ApprovalDecisionMap>({})
  const [formError, setFormError] = useState<string | null>(null)
  const [formErrorToolCallId, setFormErrorToolCallId] = useState<string | null>(null)
  const [submittingToolCallId, setSubmittingToolCallId] = useState<string | null>(null)
  const submissionInFlight = useRef(false)
  const approvalsById = useMemo(
    () => new Map(approvals.map((approval) => [approval.tool_call_id, approval])),
    [approvals]
  )
  const summary = summarizeApprovalDecisions(approvals, decisions)

  async function submit(decisionMap: ApprovalDecisionMap, toolCallId: string) {
    if (submissionInFlight.current) {
      return
    }
    setFormError(null)
    setFormErrorToolCallId(null)
    const payload = buildResumeDecisions(
      approvals,
      decisionMap,
      (toolName) => presentationFor(toolName)?.ui.arg_fields
    )
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

  function handleDecisionChange(toolCallId: string, next: ApprovalDecision) {
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
    if (activity.agentRunId !== activeRunId || !approvalsById.has(activity.id)) {
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
