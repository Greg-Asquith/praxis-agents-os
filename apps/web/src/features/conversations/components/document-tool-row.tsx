// apps/web/src/features/conversations/components/document-tool-row.tsx

import {
  FilePenLineIcon,
  FilePlus2Icon,
  FileTextIcon,
  ImageIcon,
  TableIcon,
  type LucideIcon,
} from "lucide-react"

import { DeclinedResult } from "@/components/tool-ui/declined-result"
import { FanOutSkeleton } from "@/components/tool-ui/fan-out-shell"
import { ToolResultCard } from "@/components/tool-ui/result-card"
import type { ToolApprovalDecisionControls } from "@/components/tool-ui/approval-card"
import { ApprovalDecisionBlock } from "@/features/conversations/components/approval-decision-block"
import {
  DocumentHeading,
  ImageCard,
  ReadCard,
  SaveCard,
  TableCard,
  TextList,
} from "@/features/conversations/components/document-tool-cards"
import { FailedToolCard } from "@/features/conversations/components/failed-tool-card"
import { ActivityStatusBadge } from "@/features/conversations/components/tool-activity-status"
import type { ToolActivity } from "@/features/conversations/message-parts"
import {
  documentCreateName,
  documentFileLabel,
  documentOperationSummaries,
  documentToolKind,
  documentToolResult,
  isStaleRevisionMessage,
  type DocumentToolKind,
} from "@/features/conversations/native-tools/document-tools"
import { friendlyResultText, toolUiApprovalPrompt } from "@/features/conversations/tool-ui"
import type { ToolUi } from "@/features/tools/types"

type DocumentToolRowProps = {
  activity: ToolActivity
  approvalDecision?: ToolApprovalDecisionControls
  defaultOpen: boolean
  label: string
  ui: ToolUi | null
}

export function DocumentToolRow({
  activity,
  approvalDecision,
  defaultOpen,
  label,
  ui,
}: DocumentToolRowProps) {
  const kind = documentToolKind(activity.name)
  if (!kind) return null
  if (activity.status === "awaiting_approval" && approvalDecision) {
    const prompt = ui ? toolUiApprovalPrompt(ui, activity) : null
    return (
      <ApprovalDecisionBlock
        activity={activity}
        approveLabel={ui?.approve_label ?? "Approve & Save"}
        controls={approvalDecision}
        fields={ui?.arg_fields ?? []}
        iconToken={ui?.icon ?? "file"}
        label={label}
        {...(prompt ? { prompt } : {})}
        title={ui?.approval_title ?? label}
      >
        <OperationSummary args={activity.args} />
      </ApprovalDecisionBlock>
    )
  }
  if (activity.status === "running" || activity.status === "awaiting_approval") {
    const heading = `${RUNNING_VERBS[kind]} ${callTarget(activity, kind) ?? neutralTarget(kind)}`
    return (
      <FanOutSkeleton
        heading={<DocumentHeading icon={KIND_ICONS[kind]}>{heading}</DocumentHeading>}
        label={activity.status === "running" ? `${heading}…` : "Waiting to start…"}
      />
    )
  }
  if (activity.status === "denied") return <DeclinedRow activity={activity} kind={kind} />
  if (activity.status !== "completed") {
    const target = callTarget(activity, kind)
    return (
      <FailedToolCard
        activity={activity}
        argFields={target ? [{ format: "text", key: "file", label: "File", value: target }] : []}
        defaultOpen
        iconToken={ui?.icon ?? "file"}
        label={`${ACTION_VERBS[kind]} ${target ?? neutralTarget(kind)}`}
        message={failureMessage(activity)}
      >
        <OperationSummary args={activity.args} />
      </FailedToolCard>
    )
  }
  const result = documentToolResult(activity.name, activity.result)
  if (!result) return null
  if (result.kind === "read") return <ReadCard defaultOpen={defaultOpen} result={result} />
  if (result.kind === "table") return <TableCard defaultOpen={defaultOpen} result={result} />
  if (result.kind === "image") return <ImageCard defaultOpen={defaultOpen} result={result} />
  return <SaveCard activity={activity} defaultOpen={defaultOpen} result={result} />
}

function DeclinedRow({ activity, kind }: { activity: ToolActivity; kind: DocumentToolKind }) {
  const target = callTarget(activity, kind)
  const heading = `Declined a change to ${target ?? neutralTarget(kind)}`
  return (
    <ToolResultCard
      ariaLabel={heading}
      defaultOpen
      details={target ? [{ label: "File", value: target }] : []}
      heading={<DocumentHeading icon={KIND_ICONS[kind]}>{heading}</DocumentHeading>}
      trailing={<ActivityStatusBadge status={activity.status} />}
    >
      <div className="grid min-w-0 gap-3">
        <DeclinedResult
          description="This change was declined. Nothing was saved."
          reason={activity.decisionReason}
        />
        <OperationSummary args={activity.args} />
      </div>
    </ToolResultCard>
  )
}

function failureMessage(activity: ToolActivity): string | null {
  const raw = friendlyResultText(activity.result) ?? friendlyResultText(activity.resultExcerpt)
  // Code Mode bridge errors lead with the tool name.
  const message = raw?.startsWith(`${activity.name}: `) ? raw.slice(activity.name.length + 2) : raw
  if (message && isStaleRevisionMessage(message)) {
    return "This File changed after the agent read it, so nothing was saved. The agent can read it again and redo the change."
  }
  // Tool refusals never quote file text, so they're safe to show as plain text.
  return message ?? null
}

function OperationSummary({ args }: { args: unknown }) {
  const summaries = documentOperationSummaries(args)
  return summaries.length > 0 ? <TextList items={summaries} title="Changes" /> : null
}

// Code Mode children carry no args, so the target is unknown for scripted calls.
function callTarget(activity: ToolActivity, kind: DocumentToolKind): string | null {
  return kind === "create" ? documentCreateName(activity.args) : documentFileLabel(activity.args)
}

function neutralTarget(kind: DocumentToolKind): string {
  return kind === "create" ? "a new File" : "a File"
}

const KIND_ICONS: Record<DocumentToolKind, LucideIcon> = {
  create: FilePlus2Icon,
  edit: FilePenLineIcon,
  image: ImageIcon,
  read: FileTextIcon,
  table: TableIcon,
}
const RUNNING_VERBS: Record<DocumentToolKind, string> = {
  create: "Creating",
  edit: "Editing",
  image: "Looking at an image in",
  read: "Reading",
  table: "Reading rows from",
}
const ACTION_VERBS: Record<DocumentToolKind, string> = {
  create: "Create",
  edit: "Edit",
  image: "Look at an image in",
  read: "Read",
  table: "Read rows from",
}
