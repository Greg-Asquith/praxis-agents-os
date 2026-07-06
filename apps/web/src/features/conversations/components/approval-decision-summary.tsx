// apps/web/src/features/conversations/components/approval-decision-summary.tsx

import type { ApprovalDecisionSummary } from "@/features/conversations/approval-decisions"

export function ApprovalDecisionSummaryPanel({ summary }: { summary: ApprovalDecisionSummary }) {
  return (
    <div className="min-w-0 text-sm">
      <p className="font-medium">{formatDecisionSummary(summary)}</p>
      {!summary.allDecided ? (
        <p className="text-muted-foreground mt-1">
          Choose Allow or Deny for every request before continuing.
        </p>
      ) : (
        <p className="text-muted-foreground mt-1">Every request has a decision.</p>
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
    `${String(pending)} ${pluralize("request", pending)} waiting`,
    `${String(approved)} allowed`,
    `${String(denied)} not allowed`,
  ].join(" · ")
}

function pluralize(label: string, count: number) {
  return count === 1 ? label : `${label}s`
}
