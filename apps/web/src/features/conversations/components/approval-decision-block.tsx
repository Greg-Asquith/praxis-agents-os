// apps/web/src/features/conversations/components/approval-decision-block.tsx

import type { ReactNode } from "react"

import {
  ToolApprovalDecisionCard,
  type ToolApprovalDecisionControls,
} from "@/components/tool-ui/approval-card"
import { ToolUiIcon } from "@/features/conversations/components/tool-ui-icon"
import type { ToolActivity } from "@/features/conversations/message-parts"
import type { ResolvedToolField } from "@/features/conversations/tool-ui"
import type { ToolUiField } from "@/features/tools/types"

const NO_DECLARED_FIELDS: ToolUiField[] = []
const NO_FALLBACK_FIELDS: ResolvedToolField[] = []

export type { ToolApprovalDecisionControls } from "@/components/tool-ui/approval-card"

export function ApprovalDecisionBlock({
  activity,
  approveLabel = "Approve",
  children,
  controls,
  fields = NO_DECLARED_FIELDS,
  fallbackFields = NO_FALLBACK_FIELDS,
  iconToken = null,
  label,
  prompt,
  title = label,
}: {
  activity: ToolActivity
  approveLabel?: string
  children?: ReactNode
  controls: ToolApprovalDecisionControls
  fields?: ToolUiField[]
  fallbackFields?: ResolvedToolField[]
  iconToken?: string | null
  label: string
  prompt?: string
  title?: string
}) {
  return (
    <ToolApprovalDecisionCard
      activityId={activity.id}
      approveLabel={approveLabel}
      args={activity.args}
      controls={controls}
      fallbackFields={fallbackFields}
      fields={fields}
      icon={iconToken && iconToken !== "tool" ? <ToolUiIcon token={iconToken} /> : undefined}
      label={label}
      title={title}
      {...(prompt ? { prompt } : {})}
    >
      {children}
    </ToolApprovalDecisionCard>
  )
}
