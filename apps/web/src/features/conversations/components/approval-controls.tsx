// apps/web/src/features/conversations/components/approval-controls.tsx

import { useState, type SyntheticEvent } from "react"
import { ShieldCheckIcon } from "lucide-react"

import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert"
import { Button } from "@/components/ui/button"
import {
  Card,
  CardContent,
  CardDescription,
  CardFooter,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"
import { FieldGroup } from "@/components/ui/field"
import {
  buildResumeDecisions,
  DEFAULT_APPROVAL_DECISION,
  summarizeApprovalDecisions,
  type LocalApprovalDecision,
  type LocalApprovalDecisionMap,
} from "@/features/conversations/approval-decisions"
import { ApprovalDecisionCard } from "@/features/conversations/components/approval-decision-card"
import { ApprovalDecisionSummaryPanel } from "@/features/conversations/components/approval-decision-summary"
import type { AgentRunResumeDecision, PendingToolApproval } from "@/features/conversations/types"

export function ApprovalControls({
  approvals,
  error,
  isLoading,
  isSubmitting,
  onSubmit,
}: {
  approvals: PendingToolApproval[]
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
    <form
      onSubmit={(event) => {
        void handleSubmit(event)
      }}
    >
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <ShieldCheckIcon className="size-4" />
            Approval decisions
          </CardTitle>
          <CardDescription>
            Review every pending tool request before this run continues.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <FieldGroup>
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
              <p className="text-muted-foreground rounded-lg border border-dashed p-3 text-sm">
                Loading pending approvals.
              </p>
            ) : null}
            {approvals.map((approval) => (
              <ApprovalDecisionCard
                approval={approval}
                decision={decisions[approval.tool_call_id] ?? DEFAULT_APPROVAL_DECISION}
                key={approval.tool_call_id}
                onDecisionChange={(decision) => {
                  setDecision(approval.tool_call_id, decision)
                }}
              />
            ))}
            {approvals.length > 0 ? (
              <ApprovalDecisionSummaryPanel summary={decisionSummary} />
            ) : null}
          </FieldGroup>
        </CardContent>
        <CardFooter className="justify-end">
          <Button
            disabled={
              approvals.length === 0 || isLoading || isSubmitting || !decisionSummary.allDecided
            }
            type="submit"
          >
            <ShieldCheckIcon data-icon="inline-start" />
            {submitButtonLabel({
              allDecided: decisionSummary.allDecided,
              isSubmitting,
            })}
          </Button>
        </CardFooter>
      </Card>
    </form>
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
