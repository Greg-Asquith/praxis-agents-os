// apps/web/src/features/conversations/components/approval-decision-summary.tsx

import type { ApprovalDecisionSummary } from "@/features/conversations/approval-decisions"

export function ApprovalDecisionSummaryPanel({ summary }: { summary: ApprovalDecisionSummary }) {
  return (
    <div className="bg-muted/20 rounded-lg border p-3 text-sm">
      <p className="font-medium">{formatDecisionSummary(summary)}</p>
      {!summary.allDecided ? (
        <p className="text-muted-foreground mt-1">
          Choose a decision for every request before submitting.
        </p>
      ) : (
        <p className="text-muted-foreground mt-1">All requests have an explicit decision.</p>
      )}
    </div>
  )
}

function formatDecisionSummary({
  approved,
  denied,
  pending,
}: {
  approved: number
  denied: number
  pending: number
}) {
  return [
    `${String(pending)} ${pluralize("approval", pending)} pending`,
    `${String(approved)} approved`,
    `${String(denied)} denied`,
  ].join(" · ")
}

function pluralize(label: string, count: number) {
  return count === 1 ? label : `${label}s`
}
