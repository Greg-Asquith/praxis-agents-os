// apps/web/src/features/conversations/components/approval-decision-block.tsx

import {
  approveDecision,
  denyDecision,
  type LocalApprovalDecision,
} from "@/features/conversations/approval-decisions"
import { ApprovalDecisionButtons } from "@/features/conversations/components/approval-decision-buttons"
import {
  ApprovalDenialMessageField,
  ApprovalOverrideInputField,
} from "@/features/conversations/components/approval-decision-fields"
import type { ToolActivity } from "@/features/conversations/message-parts"

export type ToolApprovalDecisionControls = {
  decision: LocalApprovalDecision
  disabled?: boolean
  onDecisionChange: (decision: LocalApprovalDecision) => void
}

export function ApprovalDecisionBlock({
  activity,
  controls,
  label,
}: {
  activity: ToolActivity
  controls: ToolApprovalDecisionControls
  label: string
}) {
  return (
    <div className="min-w-0">
      <p className="text-muted-foreground mb-2 text-xs font-medium">Decision</p>
      <div className="flex min-w-0 flex-col gap-3">
        <ApprovalDecisionButtons
          decision={controls.decision.decision}
          disabled={controls.disabled ?? false}
          label={label}
          onApprove={() => {
            controls.onDecisionChange(approveDecision(controls.decision))
          }}
          onDeny={() => {
            controls.onDecisionChange(denyDecision(controls.decision))
          }}
        />
        {controls.decision.decision === "approved" ? (
          <ApprovalOverrideInputField
            id={`${activity.id}-override`}
            onChange={(overrideArgs) => {
              controls.onDecisionChange({
                decision: "approved",
                message: "",
                overrideArgs,
              })
            }}
            value={controls.decision.overrideArgs}
          />
        ) : null}
        {controls.decision.decision === "denied" ? (
          <ApprovalDenialMessageField
            id={`${activity.id}-message`}
            onChange={(message) => {
              controls.onDecisionChange({
                decision: "denied",
                message,
                overrideArgs: "",
              })
            }}
            value={controls.decision.message}
          />
        ) : null}
        {controls.decision.decision === "pending" ? (
          <p className="text-muted-foreground bg-muted/30 rounded-md px-3 py-2 text-xs">
            Choose approve or deny for this request.
          </p>
        ) : null}
      </div>
    </div>
  )
}
