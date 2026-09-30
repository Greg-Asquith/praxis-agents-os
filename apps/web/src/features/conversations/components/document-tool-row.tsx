// apps/web/src/features/conversations/components/document-tool-row.tsx

import {
  FilePenLineIcon,
  FilePlus2Icon,
  FileTextIcon,
  ImageIcon,
  PresentationIcon,
  SheetIcon,
  TableIcon,
  TriangleAlertIcon,
  type LucideIcon,
} from "lucide-react"
import type { ReactNode } from "react"

import { DeclinedResult } from "@/components/tool-ui/declined-result"
import { FanOutSkeleton } from "@/components/tool-ui/fan-out-shell"
import { ToolResultCard, type ToolResultDetail } from "@/components/tool-ui/result-card"
import type { ToolApprovalDecisionControls } from "@/components/tool-ui/approval-card"
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert"
import { Badge } from "@/components/ui/badge"
import { ApprovalDecisionBlock } from "@/features/conversations/components/approval-decision-block"
import { FileEntityRow } from "@/features/conversations/components/file-entity-row"
import { ActivityStatusBadge } from "@/features/conversations/components/tool-activity-status"
import type { ToolActivity } from "@/features/conversations/message-parts"
import {
  documentCreateName,
  documentFileLabel,
  documentOperationSummaries,
  documentToolKind,
  documentToolResult,
  fileEntityFromDocumentResult,
  isStaleRevisionMessage,
  type DocumentImageResult,
  type DocumentReadResult,
  type DocumentSaveResult,
  type DocumentTableResult,
  type DocumentToolKind,
} from "@/features/conversations/native-tools/document-tools"
import { friendlyResultText, toolUiApprovalPrompt } from "@/features/conversations/tool-ui"
import type { ToolUi } from "@/features/tools/types"
import { pluralize } from "@/lib/format"

const VISIBLE_CHANGES = 5
const FORMAT_ICONS: Record<string, LucideIcon> = {
  pptx: PresentationIcon,
  xlsx: SheetIcon,
  docx: FileTextIcon,
}
const OUTLINE_LABELS: Record<string, string> = {
  pptx: "Slides",
  xlsx: "Sheets",
  docx: "Headings",
}

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
    const heading = `${RUNNING_VERBS[kind]} ${callTarget(activity, kind)}`
    return (
      <FanOutSkeleton
        heading={<DocumentHeading icon={KIND_ICONS[kind]}>{heading}</DocumentHeading>}
        label={activity.status === "running" ? `${heading}…` : "Waiting to start…"}
      />
    )
  }
  if (activity.status !== "completed") {
    return <FailedRow activity={activity} kind={kind} />
  }
  const result = documentToolResult(activity.name, activity.result)
  if (!result) return null
  if (result.kind === "read") return <ReadCard defaultOpen={defaultOpen} result={result} />
  if (result.kind === "table") return <TableCard defaultOpen={defaultOpen} result={result} />
  if (result.kind === "image") return <ImageCard defaultOpen={defaultOpen} result={result} />
  return <SaveCard activity={activity} defaultOpen={defaultOpen} result={result} />
}

function FailedRow({ activity, kind }: { activity: ToolActivity; kind: DocumentToolKind }) {
  const target = callTarget(activity, kind)
  const denied = activity.status === "denied"
  const heading = `${denied ? "Declined a change to" : FAILED_VERBS[kind]} ${target}`
  return (
    <ToolResultCard
      ariaLabel={heading}
      defaultOpen
      details={[{ label: "File", value: target }]}
      heading={<DocumentHeading icon={KIND_ICONS[kind]}>{heading}</DocumentHeading>}
      trailing={<ActivityStatusBadge status={activity.status} />}
    >
      <div className="grid min-w-0 gap-3">
        {denied ? (
          <DeclinedResult
            description="This change was declined. Nothing was saved."
            reason={activity.decisionReason}
          />
        ) : (
          <Alert variant="destructive">
            <TriangleAlertIcon />
            <AlertTitle>What Went Wrong</AlertTitle>
            <AlertDescription className="wrap-anywhere whitespace-pre-wrap">
              {failureMessage(activity, kind)}
            </AlertDescription>
          </Alert>
        )}
        <OperationSummary args={activity.args} />
      </div>
    </ToolResultCard>
  )
}

function failureMessage(activity: ToolActivity, kind: DocumentToolKind): string {
  const message = friendlyResultText(activity.result) ?? friendlyResultText(activity.resultExcerpt)
  if (message && isStaleRevisionMessage(message)) {
    return "This File changed after the agent read it, so nothing was saved. The agent can read it again and redo the change."
  }
  // Tool refusals never quote file text, so they're safe to show as plain text.
  if (message) return message
  return kind === "edit" || kind === "create"
    ? "The change didn't finish. Nothing was saved."
    : "The File couldn't be read."
}

function ReadCard({ defaultOpen, result }: { defaultOpen: boolean; result: DocumentReadResult }) {
  const heading = `Read ${result.file.name}`
  return (
    <DocumentCard
      badge={result.part}
      defaultOpen={defaultOpen}
      details={[
        { label: "Read", value: result.part },
        { label: "More to Read", value: result.more ? "Yes" : "No" },
        ...(result.hasTrackedChanges ? [{ label: "Tracked Changes", value: "Yes" }] : []),
      ]}
      heading={heading}
      icon={FORMAT_ICONS[result.format] ?? FileTextIcon}
      result={result}
    >
      {result.outline.length > 0 ? (
        <TextList items={result.outline} title={OUTLINE_LABELS[result.format] ?? "Contents"} />
      ) : null}
    </DocumentCard>
  )
}

function TableCard({ defaultOpen, result }: { defaultOpen: boolean; result: DocumentTableResult }) {
  const rowsLabel = `${String(result.rowsRead)} of ${String(result.totalRows)} ${pluralize(result.totalRows, "row")}`
  return (
    <DocumentCard
      badge={rowsLabel}
      defaultOpen={defaultOpen}
      details={[
        { label: "Rows Read", value: rowsLabel },
        { label: "More Rows", value: result.more ? "Yes" : "No" },
        ...(result.columns.length > 0
          ? [{ label: "Columns", value: result.columns.join(", "), summary: false }]
          : []),
        ...(result.uncalculatedCount > 0
          ? [{ label: "Formulas Without Values", value: String(result.uncalculatedCount) }]
          : []),
      ]}
      heading={`Read rows from ${result.file.name}`}
      icon={TableIcon}
      result={result}
    >
      {result.preview.length > 0 ? (
        <div className="border-border overflow-x-auto rounded-md border">
          <table className="w-full text-xs">
            <thead className="bg-muted/40">
              <tr>
                {result.columns.slice(0, result.preview[0]?.length).map((column, index) => (
                  <th
                    className="px-2 py-1 text-left font-medium"
                    key={`${String(index)}:${column}`}
                  >
                    {column}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {result.preview.map((row, rowIndex) => (
                <tr
                  className="border-border border-t"
                  key={`${String(rowIndex)}:${row.join("\t")}`}
                >
                  {row.map((cell, cellIndex) => (
                    <td
                      className="max-w-48 truncate px-2 py-1"
                      key={`${String(cellIndex)}:${cell}`}
                    >
                      {cell}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : null}
    </DocumentCard>
  )
}

function ImageCard({ defaultOpen, result }: { defaultOpen: boolean; result: DocumentImageResult }) {
  return (
    <DocumentCard
      badge={null}
      defaultOpen={defaultOpen}
      details={[{ label: "Image", value: result.imageRef }]}
      heading={`Looked at an image in ${result.file.name}`}
      icon={ImageIcon}
      result={result}
    >
      <p className="text-muted-foreground text-xs wrap-anywhere">
        The image was shared with the agent.
      </p>
    </DocumentCard>
  )
}

function SaveCard({
  activity,
  defaultOpen,
  result,
}: {
  activity: ToolActivity
  defaultOpen: boolean
  result: DocumentSaveResult
}) {
  const created = result.kind === "create"
  const template = created ? documentFileLabel(activity.args, "template_file_id") : null
  const visibleChanges = result.changes.slice(0, VISIBLE_CHANGES)
  const hiddenChanges = result.changes.length - visibleChanges.length + result.changesOmitted
  const changeCount = result.changes.length + result.changesOmitted
  const hasWarnings = result.warnings.length > 0 || result.warningsOmitted > 0
  return (
    <DocumentCard
      badge={created ? "Created" : `Version ${String(result.revisionNumber)}`}
      // Warnings open the card so they're never hidden behind the fold.
      defaultOpen={defaultOpen || hasWarnings}
      details={[
        {
          label: created ? "Created" : "Saved As",
          value: `Version ${String(result.revisionNumber)}`,
        },
        { label: "Changes", value: String(changeCount) },
        ...(hasWarnings
          ? [{ label: "Check", value: String(result.warnings.length + result.warningsOmitted) }]
          : []),
        ...(created ? [{ label: "Template", value: template ?? "Default", summary: false }] : []),
        ...(result.folder ? [{ label: "Folder", value: result.folder.name, summary: false }] : []),
      ]}
      heading={`${created ? "Created" : "Edited"} ${result.file.name}`}
      icon={created ? FilePlus2Icon : FilePenLineIcon}
      result={result}
      warning={hasWarnings}
    >
      <Warnings omitted={result.warningsOmitted} warnings={result.warnings} />
      <p className="text-muted-foreground text-xs">
        {created ? (
          <>
            {template ? `Built from ${template}` : "Built from the default template"}
            {result.folder ? (
              <>
                {" in the folder "}
                <a
                  className="text-foreground font-medium underline-offset-4 hover:underline"
                  href={`/files?folder=${encodeURIComponent(result.folder.id)}`}
                >
                  {result.folder.name}
                </a>
              </>
            ) : null}
            .
          </>
        ) : (
          <a
            className="text-foreground font-medium underline-offset-4 hover:underline"
            href={`/files?fileId=${encodeURIComponent(result.file.fileId)}`}
          >
            Saved as version {result.revisionNumber}
          </a>
        )}
      </p>
      {visibleChanges.length > 0 ? (
        <TextList
          items={[
            ...visibleChanges,
            ...(hiddenChanges > 0
              ? [`and ${String(hiddenChanges)} more ${pluralize(hiddenChanges, "change")}`]
              : []),
          ]}
          title="What Changed"
        />
      ) : null}
      {result.readback.length > 0 ? (
        <details className="min-w-0 text-xs">
          <summary className="text-muted-foreground hover:text-foreground cursor-pointer">
            Values read back after saving
          </summary>
          <dl className="mt-1.5 grid gap-1">
            {result.readback.map((item, index) => (
              <div className="grid min-w-0 gap-0.5" key={`${String(index)}:${item.label}`}>
                <dt className="font-medium">{item.label}</dt>
                <dd className="text-muted-foreground wrap-anywhere whitespace-pre-wrap">
                  {item.value || "Empty"}
                </dd>
              </div>
            ))}
          </dl>
          {result.readbackTruncated ? (
            <p className="text-muted-foreground mt-1.5">
              Some values aren't shown here. Open the File to see everything.
            </p>
          ) : null}
        </details>
      ) : null}
    </DocumentCard>
  )
}

function DocumentCard({
  badge,
  children,
  defaultOpen,
  details,
  heading,
  icon,
  result,
  warning = false,
}: {
  badge: string | null
  children?: ReactNode
  defaultOpen: boolean
  details: ToolResultDetail[]
  heading: string
  icon: LucideIcon
  result: Parameters<typeof fileEntityFromDocumentResult>[0]
  warning?: boolean
}) {
  return (
    <ToolResultCard
      ariaLabel={heading}
      defaultOpen={defaultOpen}
      details={details}
      heading={<DocumentHeading icon={icon}>{heading}</DocumentHeading>}
      trailing={
        badge ? (
          <Badge className="shrink-0" variant={warning ? "warning" : "success"}>
            {badge}
          </Badge>
        ) : null
      }
    >
      <div className="grid min-w-0 gap-3">
        <FileEntityRow file={fileEntityFromDocumentResult(result)} />
        {children}
      </div>
    </ToolResultCard>
  )
}

function Warnings({ omitted, warnings }: { omitted: number; warnings: string[] }) {
  if (warnings.length === 0 && omitted === 0) return null
  return (
    <Alert>
      <TriangleAlertIcon className="text-warning" />
      <AlertTitle>Check</AlertTitle>
      <AlertDescription>
        <ul className="grid gap-0.5">
          {warnings.map((warning, index) => (
            <li className="wrap-anywhere" key={`${String(index)}:${warning}`}>
              {warning}
            </li>
          ))}
          {omitted > 0 ? (
            <li>
              and {omitted} more {pluralize(omitted, "warning")}
            </li>
          ) : null}
        </ul>
      </AlertDescription>
    </Alert>
  )
}

function OperationSummary({ args }: { args: unknown }) {
  const summaries = documentOperationSummaries(args)
  return summaries.length > 0 ? <TextList items={summaries} title="Changes" /> : null
}

function TextList({ items, title }: { items: string[]; title: string }) {
  return (
    <section className="grid gap-1">
      <h4 className="text-xs font-medium">{title}</h4>
      <ul className="text-muted-foreground grid list-disc gap-0.5 pl-4 text-xs">
        {items.map((item, index) => (
          <li className="wrap-anywhere" key={`${String(index)}:${item}`}>
            {item}
          </li>
        ))}
      </ul>
    </section>
  )
}

function DocumentHeading({ children, icon: Icon }: { children: string; icon: LucideIcon }) {
  return (
    <span className="inline-flex min-w-0 items-center gap-2">
      <Icon className="text-muted-foreground size-4 shrink-0" />
      <span className="truncate">{children}</span>
    </span>
  )
}

function callTarget(activity: ToolActivity, kind: DocumentToolKind): string {
  return kind === "create"
    ? (documentCreateName(activity.args) ?? "a new File")
    : (documentFileLabel(activity.args) ?? "a File")
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
const FAILED_VERBS: Record<DocumentToolKind, string> = {
  create: "Couldn't create",
  edit: "Couldn't edit",
  image: "Couldn't show an image from",
  read: "Couldn't read",
  table: "Couldn't read rows from",
}
