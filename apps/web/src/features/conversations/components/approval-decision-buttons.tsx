// apps/web/src/features/conversations/components/approval-decision-buttons.tsx

import { CheckIcon, XIcon } from "lucide-react"

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
      className="grid w-full min-w-0 grid-cols-2 gap-2 md:w-56"
      role="group"
    >
      <Button
        aria-pressed={decision === "approved"}
        disabled={disabled}
        onClick={onApprove}
        size="sm"
        type="button"
        variant={decision === "approved" ? "default" : "outline"}
      >
        <CheckIcon data-icon="inline-start" />
        Approve
      </Button>
      <Button
        aria-pressed={decision === "denied"}
        disabled={disabled}
        onClick={onDeny}
        size="sm"
        type="button"
        variant={decision === "denied" ? "destructive" : "outline"}
      >
        <XIcon data-icon="inline-start" />
        Deny
      </Button>
    </div>
  )
}
