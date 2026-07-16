// apps/web/src/features/conversations/components/approval-decision-buttons.tsx

import { Button } from "@/components/ui/button"
import type { LocalApprovalDecision } from "@/features/conversations/approval-decisions"

export function ApprovalDecisionButtons({
  disabled = false,
  decision,
  label,
  onApprove,
  onDeny,
}: {
  disabled?: boolean
  decision: LocalApprovalDecision["decision"]
  label: string
  onApprove: () => void
  onDeny: () => void
}) {
  return (
    <div
      aria-label={`Decision for ${label}`}
      className="flex w-full min-w-0 items-center justify-end gap-1 sm:w-auto"
      role="group"
    >
      <Button
        aria-pressed={decision === "denied"}
        disabled={disabled}
        onClick={onDeny}
        size="sm"
        type="button"
        variant={decision === "denied" ? "secondary" : "ghost"}
      >
        Decline
      </Button>
      <Button
        aria-pressed={decision === "approved"}
        disabled={disabled}
        onClick={onApprove}
        size="sm"
        type="button"
        variant={decision === "approved" ? "default" : "secondary"}
      >
        Approve
      </Button>
    </div>
  )
}
