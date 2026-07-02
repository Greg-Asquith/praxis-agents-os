// apps/web/src/features/conversations/components/approval-controls.tsx

import { useState, type SyntheticEvent } from "react"
import { ShieldCheckIcon } from "lucide-react"

import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert"
import { Button } from "@/components/ui/button"
import {
  buildResumeDecisions,
  DEFAULT_APPROVAL_DECISION,
  summarizeApprovalDecisions,
  type LocalApprovalDecision,
  type LocalApprovalDecisionMap,
} from "@/features/conversations/approval-decisions"
import { ApprovalDecisionSummaryPanel } from "@/features/conversations/components/approval-decision-summary"
import { AssistantMessageShell } from "@/features/conversations/components/message-shell"
import { ToolCallRow } from "@/features/conversations/components/tool-call-row"
import { normalizeToolArgs } from "@/features/conversations/message-parts"
import type { AgentRunResumeDecision, PendingToolApproval } from "@/features/conversations/types"

export function ApprovalControls({
  approvals,
  assistantLabel,
  error,
  isLoading,
  isSubmitting,
  onSubmit,
}: {
  approvals: PendingToolApproval[]
  assistantLabel: string
  error: string | null
  isLoading: boolean
  isSubmitting: boolean
  onSubmit: (decisions: AgentRunResumeDecision[]) => Promise<void>
}) {
  const [decisions, setDecisions] = useState<LocalApprovalDecisionMap>({})
  const [formError, setFormError] = useState<string | null>(null)
  const decisionSummary = summarizeApprovalDecisions(approvals, decisions)

  async function handleSubmit(event: SyntheticEvent<HTMLFormElement>) {
    event.preventDefault()
    setFormError(null)

    const payload = buildResumeDecisions(approvals, decisions)
    if (typeof payload === "string") {
      setFormError(payload)
      return
    }

    try {
      await onSubmit(payload)
    } catch (submitError) {
      setFormError(submitError instanceof Error ? submitError.message : "Approval submit failed.")
    }
  }

  if (approvals.length === 0 && !isLoading && !error) {
    return null
  }

  return (
    <AssistantMessageShell createdAt={null} label={assistantLabel}>
      <form
        aria-label="Pending approval decisions"
        className="flex min-w-0 flex-col gap-3"
        onSubmit={(event) => {
          void handleSubmit(event)
        }}
      >
        {error ? (
          <Alert variant="destructive">
            <AlertTitle>Approval state unavailable</AlertTitle>
            <AlertDescription>{error}</AlertDescription>
          </Alert>
        ) : null}
        {formError ? (
          <Alert variant="destructive">
            <AlertTitle>Run not resumed</AlertTitle>
            <AlertDescription>{formError}</AlertDescription>
          </Alert>
        ) : null}
        {isLoading ? (
          <p className="text-muted-foreground bg-muted/50 rounded-lg px-3 py-2 text-sm">
            Loading pending approvals.
          </p>
        ) : null}
        {approvals.map((approval) => {
          const decision = decisions[approval.tool_call_id] ?? DEFAULT_APPROVAL_DECISION
          return (
            <ToolCallRow
              activity={{
                args: normalizeToolArgs(approval.args),
                id: approval.tool_call_id,
                kind: "approval",
                name: approval.name,
                status: "awaiting_approval",
              }}
              approvalDecision={{
                decision,
                disabled: isSubmitting,
                onDecisionChange: (nextDecision) => {
                  setDecision(approval.tool_call_id, nextDecision)
                },
              }}
              defaultOpen
              key={approval.tool_call_id}
            />
          )
        })}

        {approvals.length > 0 ? (
          <div className="border-border/70 flex min-w-0 flex-col gap-3 border-t pt-3 sm:flex-row sm:items-center sm:justify-between">
            <ApprovalDecisionSummaryPanel summary={decisionSummary} />
            <Button
              className="w-full sm:w-auto"
              disabled={isLoading || isSubmitting || !decisionSummary.allDecided}
              type="submit"
            >
              <ShieldCheckIcon data-icon="inline-start" />
              {submitButtonLabel({
                allDecided: decisionSummary.allDecided,
                isSubmitting,
              })}
            </Button>
          </div>
        ) : null}
      </form>
    </AssistantMessageShell>
  )

  function setDecision(toolCallId: string, decision: LocalApprovalDecision) {
    setDecisions((current) => ({ ...current, [toolCallId]: decision }))
  }
}

function submitButtonLabel({
  allDecided,
  isSubmitting,
}: {
  allDecided: boolean
  isSubmitting: boolean
}) {
  if (isSubmitting) {
    return "Submitting decisions"
  }

  return allDecided ? "Submit decisions" : "Choose decisions"
}
