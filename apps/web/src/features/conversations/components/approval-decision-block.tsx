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
import { cn } from "@/lib/utils"

export type ToolApprovalDecisionControls = {
  decision: LocalApprovalDecision
  disabled?: boolean
  onDecisionChange: (decision: LocalApprovalDecision) => void
}

export function ApprovalDecisionBlock({
  activity,
  controls,
  label,
  prompt,
}: {
  activity: ToolActivity
  controls: ToolApprovalDecisionControls
  label: string
  prompt?: string
}) {
  return (
    <div
      className={cn(
        "bg-card min-w-0 rounded-lg border px-4 py-3 shadow-xs",
        activity.status === "awaiting_approval" && "border-warning/40"
      )}
    >
      <div className="flex min-w-0 flex-col gap-3">
        <div className="flex min-w-0 flex-wrap items-center justify-between gap-2">
          <p className="text-foreground min-w-0 flex-1 text-sm">
            {prompt ?? `The agent is asking to use ${label}.`}
          </p>
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
        </div>
        {controls.decision.decision !== "denied" ? (
          <ApprovalOverrideInputField
            id={`${activity.id}-override`}
            onChange={(overrideArgs) => {
              controls.onDecisionChange({
                decision: controls.decision.decision === "approved" ? "approved" : "pending",
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
      </div>
    </div>
  )
}
