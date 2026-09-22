// apps/web/src/features/conversations/hooks/use-inline-approvals.ts

import { useLayoutEffect, useMemo, useRef, useState } from "react"

import { ApiError } from "@/lib/api/errors"
import type { ApprovalDecision } from "@/components/tool-ui/approval-card"
import type { ApprovalDecisionResolver } from "@/features/conversations/approval-decision-context"
import {
  approvalDecisionKey,
  hasAmbiguousApprovals,
  buildResumeDecisions,
  DEFAULT_APPROVAL_DECISION,
  shouldSubmitDecisions,
  summarizeApprovalDecisions,
  type ApprovalDecisionMap,
} from "@/features/conversations/approval-decisions"
import type { AgentRunResumeDecision, PendingToolApproval } from "@/features/conversations/types"
import type { ToolPresentationEntry } from "@/features/tools/types"
import type { ApprovalReviewInput } from "@/features/conversations/api/review-approval"
import { isRecord } from "@/lib/guards"

const NO_PRESENTATION = () => null

type UseInlineApprovalsParams = {
  approvalRevision?: string | null
  readOnly?: boolean
  activeRunId: string | null
  approvals: PendingToolApproval[]
  enabled: boolean
  isSubmitting: boolean
  onSubmit: (decisions: AgentRunResumeDecision[], revision?: string) => Promise<void>
  onReview?: (input: ApprovalReviewInput) => Promise<void>
  presentationFor?: (name: string) => ToolPresentationEntry | null
}

export function useInlineApprovals({
  activeRunId,
  approvalRevision,
  readOnly = false,
  approvals,
  enabled,
  isSubmitting,
  onSubmit,
  onReview,
  presentationFor = NO_PRESENTATION,
}: UseInlineApprovalsParams) {
  const scope = JSON.stringify([activeRunId, approvalRevision])
  const [previousScope, setPreviousScope] = useState(scope)
  const [decisions, setDecisions] = useState<ApprovalDecisionMap>({})
  const [formError, setFormError] = useState<string | null>(null)
  const [formErrorToolCallId, setFormErrorToolCallId] = useState<string | null>(null)
  const [reviewErrorKey, setReviewErrorKey] = useState<string | null>(null)
  const [submittingToolCallId, setSubmittingToolCallId] = useState<string | null>(null)
  if (previousScope !== scope) {
    setPreviousScope(scope)
    setDecisions({})
    setFormError(null)
    setFormErrorToolCallId(null)
    setReviewErrorKey(null)
  }
  const currentScope = useRef(scope)
  useLayoutEffect(() => {
    currentScope.current = scope
  }, [scope])
  const submissionInFlight = useRef(false)
  const ambiguous = hasAmbiguousApprovals(approvals)
  const reviewEnabled = useRef(false)
  useLayoutEffect(() => {
    reviewEnabled.current = !readOnly && enabled && !ambiguous && !isSubmitting
    return () => {
      reviewEnabled.current = false
    }
  }, [readOnly, enabled, ambiguous, isSubmitting])
  const approvalsById = useMemo(
    () => new Map(approvals.map((approval) => [approvalDecisionKey(approval), approval])),
    [approvals]
  )
  const summary = summarizeApprovalDecisions(approvals, decisions)

  async function submit(decisionMap: ApprovalDecisionMap, toolCallId: string) {
    if (
      readOnly ||
      isSubmitting ||
      !enabled ||
      ambiguous ||
      currentScope.current !== scope ||
      submissionInFlight.current
    ) {
      return
    }
    setFormError(null)
    setFormErrorToolCallId(null)
    setReviewErrorKey(null)
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
      await onSubmit(payload, approvalRevision ?? undefined)
      if (currentScope.current === scope) setDecisions({})
    } catch (submitError) {
      if (currentScope.current !== scope) return
      if (
        submitError instanceof Error &&
        submitError.cause instanceof ApiError &&
        submitError.cause.status === 409
      ) {
        setDecisions({})
      }
      setFormError(submitError instanceof Error ? submitError.message : "Approval submit failed.")
      setFormErrorToolCallId(toolCallId)
    } finally {
      submissionInFlight.current = false
      setSubmittingToolCallId(null)
    }
  }

  function handleDecisionChange(toolCallId: string, next: ApprovalDecision) {
    if (
      readOnly ||
      !enabled ||
      ambiguous ||
      currentScope.current !== scope ||
      submissionInFlight.current
    )
      return
    setFormError(null)
    setReviewErrorKey(null)
    const previous = decisions[toolCallId] ?? DEFAULT_APPROVAL_DECISION
    const nextDecisions = { ...decisions, [toolCallId]: next }
    setDecisions(nextDecisions)

    if (
      shouldSubmitDecisions(previous, next, summarizeApprovalDecisions(approvals, nextDecisions))
    ) {
      void submit(nextDecisions, toolCallId)
    }
  }

  async function review(approval: PendingToolApproval, key: string) {
    if (
      !onReview ||
      !activeRunId ||
      !approvalRevision ||
      !approval.approval_id ||
      !reviewEnabled.current ||
      submissionInFlight.current ||
      currentScope.current !== scope
    )
      return
    const decision = decisions[key] ?? DEFAULT_APPROVAL_DECISION
    if (decision.decision !== "pending") return
    if (!isRecord(approval.replay_args)) {
      setFormError("These details cannot be reviewed. Refresh the conversation.")
      setFormErrorToolCallId(key)
      return
    }
    const merged = buildResumeDecisions(
      [approval],
      { [key]: { ...decision, decision: "approved" } },
      (name) => presentationFor(name)?.ui.arg_fields
    )
    const args =
      typeof merged === "string" ? null : (merged[0]?.override_args ?? approval.replay_args)
    if (!isRecord(args)) {
      setFormError(
        typeof merged === "string"
          ? merged
          : "These details cannot be reviewed. Refresh the conversation."
      )
      setFormErrorToolCallId(key)
      return
    }
    submissionInFlight.current = true
    setSubmittingToolCallId(key)
    setFormError(null)
    setReviewErrorKey(null)
    try {
      await onReview({
        runId: activeRunId,
        approval_revision: approvalRevision,
        approval_id: approval.approval_id,
        override_args: args,
      })
    } catch (error) {
      if (currentScope.current === scope) {
        setFormError(
          error instanceof Error ? error.message : "The selected File could not be reviewed."
        )
        setFormErrorToolCallId(key)
        setReviewErrorKey(key)
      }
    } finally {
      submissionInFlight.current = false
      setSubmittingToolCallId(null)
    }
  }

  const resolveApprovalControls: ApprovalDecisionResolver = (activity) => {
    if (readOnly || !enabled || activity.status !== "awaiting_approval") {
      return null
    }
    if ((activity.rootRunId ?? activity.agentRunId) !== activeRunId) return null
    const key = activity.approvalId ?? activity.id
    const approval = approvalsById.get(key)
    if (!approval || (approval.owner_run_id && approval.owner_run_id !== activity.agentRunId))
      return null

    return {
      formKey: JSON.stringify([activeRunId, approvalRevision, key]),
      decision: decisions[key] ?? DEFAULT_APPROVAL_DECISION,
      disabled: ambiguous || isSubmitting || submittingToolCallId !== null,
      error: ambiguous
        ? "These requests cannot be reviewed separately. Refresh the conversation before approving."
        : formErrorToolCallId === key
          ? formError
          : null,
      pendingCount: summary.pending,
      submitting: submittingToolCallId === key,
      onDecisionChange: (next) => {
        handleDecisionChange(key, next)
      },
      onRetry: () => {
        if (reviewErrorKey === key) void review(approval, key)
        else void submit(decisions, key)
      },
      ...(onReview
        ? {
            onReview: () => {
              void review(approval, key)
            },
          }
        : {}),
    }
  }

  return {
    resolveApprovalControls,
    unavailableReason: ambiguous
      ? "These requests cannot be reviewed separately. Refresh the conversation before approving."
      : null,
  }
}
