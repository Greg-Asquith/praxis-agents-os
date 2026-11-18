// apps/web/src/features/conversations/components/video-generation-approval.tsx

import { approvalFallbackFields } from "@/components/tool-ui/approval-fallback-fields"
import type { ToolApprovalDecisionControls } from "@/components/tool-ui/approval-card"
import type { EditedValues } from "@/components/tool-ui/edited-values"
import { ApprovalDecisionBlock } from "@/features/conversations/components/approval-decision-block"
import type { ToolActivity } from "@/features/conversations/message-parts"
import { toolUiApprovalPrompt } from "@/features/conversations/tool-ui"
import type { VideoCostEstimate } from "@/features/conversations/native-tools/video-tools"
import type { ToolUi } from "@/features/tools/types"

// The declared fields, with the call's estimated cost under them, following the approver's edits.
export function VideoGenerationApproval({
  activity,
  controls,
  estimate,
  label,
  ui,
}: {
  activity: ToolActivity
  controls: ToolApprovalDecisionControls
  estimate: (args: unknown, edits: EditedValues) => VideoCostEstimate | null
  label: string
  ui: ToolUi | null
}) {
  const fields = ui?.arg_fields ?? []
  const cost = estimate(activity.args, controls.decision.edits)
  const prompt = ui ? toolUiApprovalPrompt(ui, activity) : null
  return (
    <ApprovalDecisionBlock
      activity={activity}
      approveLabel={ui?.approve_label ?? "Approve"}
      controls={controls}
      fallbackFields={approvalFallbackFields(activity.args, fields)}
      fields={fields}
      iconToken={ui?.icon ?? "video"}
      label={label}
      {...(prompt ? { prompt } : {})}
      title={ui?.approval_title ?? label}
    >
      {cost ? (
        <dl className="grid grid-cols-[auto_1fr] gap-x-4 text-sm">
          <dt className="text-muted-foreground">Estimated Cost</dt>
          <dd className="min-w-0 wrap-break-word">
            About ${cost.usd} <span className="text-muted-foreground">· {cost.basis}</span>
          </dd>
        </dl>
      ) : null}
    </ApprovalDecisionBlock>
  )
}
