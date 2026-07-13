// apps/web/src/features/conversations/components/tool-call-row.tsx

import { use } from "react"

import { ApprovalDecisionContext } from "@/features/conversations/approval-decision-context"
import { ApprovalDecisionBlock } from "@/features/conversations/components/approval-decision-block"
import { TextBlock } from "@/features/conversations/components/tool-call-content-blocks"
import { renderCustomToolCallRow } from "@/features/conversations/components/tool-call-row-registry"
import {
  TechnicalDetails,
  ToolFieldList,
} from "@/features/conversations/components/tool-friendly-blocks"
import { ToolUiIcon } from "@/features/conversations/components/tool-ui-icon"
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
import { normalizeToolArgs } from "@/features/conversations/message-parts"
import {
  autoUiFields,
  friendlyResultText,
  resolveUiFields,
  toolUiApprovalPrompt,
  toolUiStatusLabel,
} from "@/features/conversations/tool-ui"
import type { ToolUi } from "@/features/tools/types"
import { useToolPresentations } from "@/features/tools/use-tool-presentations"

type ToolCallRowProps = {
  activity: ToolActivity
  compact?: boolean
  defaultOpen?: boolean
}

export function ToolCallRow({ activity, compact = false, defaultOpen = false }: ToolCallRowProps) {
  const presentationFor = useToolPresentations()
  const approvalDecision = use(ApprovalDecisionContext)(activity) ?? undefined
  const shouldOpen = defaultOpen || approvalDecision !== undefined
  const customRow = renderCustomToolCallRow({
    activity,
    ...(approvalDecision ? { approvalDecision } : {}),
    compact,
    defaultOpen: shouldOpen,
  })
  if (customRow) {
    return customRow
  }

  const entry = presentationFor(activity.name)
  const ui = entry?.ui ?? null
  const title = entry?.label ?? activity.name
  const supportLabel = entry ? null : supportIdentifier(activity.name)
  const normalizedArgs = normalizeToolArgs(activity.args)

  const hasArgs = activity.args !== undefined && activity.args !== null
  const hasResult = activity.result !== undefined && activity.result !== null
  const expandable = hasArgs || hasResult || approvalDecision !== undefined

  const argFields = ui?.arg_fields.length
    ? resolveUiFields(ui.arg_fields, activity.args)
    : autoUiFields(activity.args)
  const resultFields = ui?.result_fields.length
    ? resolveUiFields(ui.result_fields, activity.result)
    : []
  const resultText = resultFields.length === 0 ? friendlyResultText(activity.result) : null
  const approvalPrompt = ui
    ? (toolUiApprovalPrompt(ui, activity) ?? fallbackApprovalPrompt(title))
    : fallbackApprovalPrompt(title)

  const header = (
    <ToolActivityRowHeader
      expandable={expandable}
      icon={<ActivityStatusIcon fallbackIcon="tool" status={activity.status} />}
      label={
        <span className="inline-flex min-w-0 items-center gap-1.5">
          <ToolUiIcon token={ui?.icon ?? null} />
          <span className="min-w-0 truncate">{headlineForActivity(activity, title, ui)}</span>
        </span>
      }
      suffix={<ActivityStatusSuffix status={activity.status} suffix={toolStatusSuffix(activity)} />}
      supportLabel={supportLabel}
    />
  )

  return (
    <ToolActivityRowShell
      compact={compact}
      defaultOpen={shouldOpen}
      expandable={expandable}
      header={header}
    >
      <ToolFieldList fields={argFields} />
      {approvalDecision ? (
        <ApprovalDecisionBlock
          activity={activity}
          controls={approvalDecision}
          label={title}
          prompt={approvalPrompt}
        />
      ) : null}
      <ToolFieldList fields={resultFields} />
      {resultText ? <TextBlock label="Result" value={resultText} /> : null}
      <TechnicalDetails args={normalizedArgs} result={activity.result} />
    </ToolActivityRowShell>
  )
}

function headlineForActivity(activity: ToolActivity, title: string, ui: ToolUi | null) {
  if (activity.status === "awaiting_approval" && ui?.approval_title) {
    return `Permission needed: ${ui.approval_title}`
  }
  const uiLabel = ui ? toolUiStatusLabel(ui, activity) : null
  return uiLabel ?? `${toolActivityVerb(activity)} ${title}`
}

function fallbackApprovalPrompt(title: string) {
  return `The agent is asking to use ${title}.`
}
