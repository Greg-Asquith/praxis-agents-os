// apps/web/src/features/conversations/components/tool-call-row.tsx

import {
  ApprovalDecisionBlock,
  type ToolApprovalDecisionControls,
} from "@/features/conversations/components/approval-decision-block"
import { JsonBlock, TextBlock } from "@/features/conversations/components/tool-call-content-blocks"
import { renderCustomToolCallRow } from "@/features/conversations/components/tool-call-row-registry"
import {
  ToolActivityRowHeader,
  ToolActivityRowShell,
} from "@/features/conversations/components/tool-activity-row-shell"
import {
  ActivityStatusIcon,
  ActivityStatusSuffix,
} from "@/features/conversations/components/tool-activity-status"
import {
  toolActivityVerb,
  toolStatusSuffix,
} from "@/features/conversations/components/tool-activity-status-values"
import { supportIdentifier } from "@/features/conversations/format"
import type { ToolActivity } from "@/features/conversations/message-parts"
import { useToolLabels } from "@/features/tools/use-tool-labels"

type ToolCallRowProps = {
  approvalDecision?: ToolApprovalDecisionControls
  activity: ToolActivity
  compact?: boolean
  defaultOpen?: boolean
}

export function ToolCallRow({
  activity,
  approvalDecision,
  compact = false,
  defaultOpen = false,
}: ToolCallRowProps) {
  const toolLabelFor = useToolLabels()
  const customRow = renderCustomToolCallRow({
    activity,
    ...(approvalDecision ? { approvalDecision } : {}),
    compact,
    defaultOpen,
  })
  if (customRow) {
    return customRow
  }

  const title = toolLabelFor(activity.name)
  const supportLabel = title === activity.name ? supportIdentifier(activity.name) : null
  const hasArgs = activity.args !== undefined && activity.args !== null
  const hasResult = activity.result !== undefined && activity.result !== null
  const decisionLabel = decisionForActivity(activity)
  const expandable =
    hasArgs || hasResult || decisionLabel !== null || approvalDecision !== undefined
  const header = (
    <ToolActivityRowHeader
      expandable={expandable}
      icon={<ActivityStatusIcon fallbackIcon="tool" status={activity.status} />}
      label={
        <>
          {toolActivityVerb(activity)} {title}
        </>
      }
      suffix={<ActivityStatusSuffix status={activity.status} suffix={toolStatusSuffix(activity)} />}
      supportLabel={supportLabel}
    />
  )

  return (
    <ToolActivityRowShell
      compact={compact}
      defaultOpen={defaultOpen}
      expandable={expandable}
      header={header}
    >
      {hasArgs && <JsonBlock label="Input" value={activity.args} />}
      {approvalDecision ? (
        <ApprovalDecisionBlock activity={activity} controls={approvalDecision} label={title} />
      ) : decisionLabel ? (
        <TextBlock label="Decision" value={decisionLabel} />
      ) : null}
      {hasResult && <JsonBlock label="Output" value={activity.result} />}
    </ToolActivityRowShell>
  )
}

function decisionForActivity(activity: ToolActivity) {
  if (activity.decision === "approved") {
    return "Approved"
  }
  if (activity.decision === "denied") {
    return "Denied"
  }
  if (activity.status === "awaiting_approval") {
    return "Waiting for approval"
  }
  if (activity.status === "denied") {
    return "Denied"
  }
  return null
}
