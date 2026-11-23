// apps/web/src/features/conversations/components/tools/video/video-clips-approval.tsx

import { approvalFallbackFields } from "@/components/tool-ui/approval-fallback-fields"
import type { ToolApprovalDecisionControls } from "@/components/tool-ui/approval-card"
import { DataTable, type DataColumn, type DataRow } from "@/components/ui/data-table"
import { ApprovalDecisionBlock } from "@/features/conversations/components/tool-rows/approval-decision-block"
import type { ToolActivity } from "@/features/conversations/message-parts"
import {
  type CutVideoClipsPlan,
  cutVideoClipsPlan,
} from "@/features/conversations/native-tools/video-tools"
import type { ToolUi } from "@/features/tools/types"

const COLUMNS: DataColumn[] = [
  { key: "clip", kind: "text", label: "Clip" },
  { key: "segments", kind: "text", label: "Segments", width: "auto" },
  { key: "finishing", kind: "text", label: "Finishing" },
  { key: "text", kind: "text", label: "Text on Screen" },
]

export function CutVideoClipsApproval({
  activity,
  controls,
  label,
  ui,
}: {
  activity: ToolActivity
  controls: ToolApprovalDecisionControls
  label: string
  ui: ToolUi | null
}) {
  const fields = ui?.arg_fields ?? []
  const plan = cutVideoClipsPlan(activity.args)
  return (
    <ApprovalDecisionBlock
      activity={activity}
      approveLabel={ui?.approve_label ?? "Approve & Cut"}
      controls={controls}
      fallbackFields={approvalFallbackFields(activity.args, fields)}
      fields={fields}
      iconToken={ui?.icon ?? "video"}
      label={label}
      prompt={
        ui?.approval_prompt ?? "The agent wants to cut clips from workspace videos and save them."
      }
      title={ui?.approval_title ?? "Cut Video Clips"}
    >
      {plan ? <ClipsPlan plan={plan} /> : null}
    </ApprovalDecisionBlock>
  )
}

// Every finishing option the call applies: once for every clip, then each clip's own.
function ClipsPlan({ plan }: { plan: CutVideoClipsPlan }) {
  const shared = [
    { label: "Sound", value: plan.sound },
    ...(plan.music ? [{ label: "Music", value: plan.music }] : []),
    ...(plan.logo ? [{ label: "Logo", value: plan.logo }] : []),
    ...(plan.pausesRemoved ? [{ label: "Pauses", value: "Removed" }] : []),
    ...(plan.punchIns ? [{ label: "Punch-In Zooms", value: "On" }] : []),
    ...(plan.blackBars ? [{ label: "Black Bars", value: plan.blackBars }] : []),
  ]
  const rows = plan.clips.map<DataRow>((clip) => ({
    clip: clip.name ?? `Clip ${String(clip.index)}`,
    segments: clip.ranges.join(" + "),
    finishing: clip.effects.join(" · ") || "—",
    text: clip.overlays.map((overlay) => `“${overlay}”`).join(" · ") || "—",
  }))
  return (
    <div className="grid min-w-0 gap-3">
      <dl aria-label="Every clip" className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1 text-sm">
        {shared.map((item) => (
          <div className="contents" key={item.label}>
            <dt className="text-muted-foreground">{item.label}</dt>
            <dd className="min-w-0 wrap-break-word">{item.value}</dd>
          </div>
        ))}
      </dl>
      <DataTable columns={COLUMNS} rowNoun={["clip", "clips"]} rows={rows} />
    </div>
  )
}
