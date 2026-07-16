// apps/web/src/features/conversations/components/approval-submit-bar.tsx

import { ShieldCheckIcon } from "lucide-react"

import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert"
import { Button } from "@/components/ui/button"
import type { ApprovalDecisionSummary } from "@/features/conversations/approval-decisions"
import { pluralize } from "@/lib/format"

export function ApprovalSubmitBar({
  error,
  isSubmitting,
  onSubmit,
  summary,
}: {
  error: string | null
  isSubmitting: boolean
  onSubmit: () => void
  summary: ApprovalDecisionSummary
}) {
  return (
    <div className="border-border/60 ml-6 flex min-w-0 flex-col gap-2 border-l pl-3">
      {error ? (
        <Alert variant="destructive">
          <AlertTitle>Run not resumed</AlertTitle>
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      ) : null}
      <div className="flex min-w-0 flex-wrap items-center justify-end gap-3">
        {summary.pending > 0 ? (
          <span className="text-muted-foreground text-xs">
            {String(summary.pending)} {pluralize(summary.pending, "request")} still{" "}
            {summary.pending === 1 ? "needs" : "need"} a decision.
          </span>
        ) : null}
        <Button disabled={isSubmitting || !summary.allDecided} onClick={onSubmit} size="sm">
          <ShieldCheckIcon data-icon="inline-start" />
          {isSubmitting ? "Sending Decisions" : "Send Decisions"}
        </Button>
      </div>
    </div>
  )
}
