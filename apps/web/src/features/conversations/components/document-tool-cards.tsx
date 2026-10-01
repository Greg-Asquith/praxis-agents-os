// apps/web/src/features/conversations/components/document-tool-cards.tsx

import { Link } from "@tanstack/react-router"
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

import { ToolResultCard, type ToolResultDetail } from "@/components/tool-ui/result-card"
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert"
import { Badge } from "@/components/ui/badge"
import { FileEntityRow } from "@/features/conversations/components/file-entity-row"
import type { ToolActivity } from "@/features/conversations/message-parts"
import {
  documentFileLabel,
  fileEntityFromDocumentResult,
  type DocumentImageResult,
  type DocumentReadResult,
  type DocumentSaveResult,
  type DocumentTableResult,
} from "@/features/conversations/native-tools/document-tools"
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
const LINK_CLASS = "text-foreground font-medium underline-offset-4 hover:underline"

export function ReadCard({
  defaultOpen,
  result,
}: {
  defaultOpen: boolean
  result: DocumentReadResult
}) {
  return (
    <DocumentCard
      badge={result.part}
      defaultOpen={defaultOpen}
      details={[
        { label: "More to Read", value: result.more ? "Yes" : "No" },
        ...(result.hasTrackedChanges ? [{ label: "Tracked Changes", value: "Yes" }] : []),
      ]}
      heading={`Read ${result.file.name}`}
      icon={FORMAT_ICONS[result.format] ?? FileTextIcon}
      result={result}
    >
      {result.outline.length > 0 ? (
        <TextList items={result.outline} title={OUTLINE_LABELS[result.format] ?? "Contents"} />
      ) : null}
    </DocumentCard>
  )
}

export function TableCard({
  defaultOpen,
  result,
}: {
  defaultOpen: boolean
  result: DocumentTableResult
}) {
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

export function ImageCard({
  defaultOpen,
  result,
}: {
  defaultOpen: boolean
  result: DocumentImageResult
}) {
  return (
    <DocumentCard
      badge={null}
      defaultOpen={defaultOpen}
      details={[]}
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

export function SaveCard({
  activity,
  defaultOpen,
  result,
}: {
  activity: ToolActivity
  defaultOpen: boolean
  result: DocumentSaveResult
}) {
  const created = result.kind === "create"
  // Code Mode children carry no args, so the template is only known for direct calls.
  const hasArgs = activity.args !== undefined && activity.args !== null
  const template = created && hasArgs ? documentFileLabel(activity.args, "template_file_id") : null
  const templateLabel = created && hasArgs ? (template ?? "Default") : null
  const source =
    created && hasArgs
      ? template
        ? `Built from ${template}`
        : "Built from the default template"
      : null
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
        ...(templateLabel ? [{ label: "Template", value: templateLabel, summary: false }] : []),
        ...(result.folder ? [{ label: "Folder", value: result.folder.name, summary: false }] : []),
      ]}
      heading={`${created ? "Created" : "Edited"} ${result.file.name}`}
      icon={created ? FilePlus2Icon : FilePenLineIcon}
      result={result}
      warning={hasWarnings}
    >
      <Warnings omitted={result.warningsOmitted} warnings={result.warnings} />
      <SaveSummary result={result} source={source} />
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

function SaveSummary({ result, source }: { result: DocumentSaveResult; source: string | null }) {
  if (result.kind === "edit") {
    return (
      <p className="text-muted-foreground text-xs">
        <Link className={LINK_CLASS} search={{ fileId: result.file.fileId }} to="/files">
          Saved as version {result.revisionNumber}
        </Link>
      </p>
    )
  }
  const folder = result.folder
  if (!source && !folder) return null
  return (
    <p className="text-muted-foreground text-xs">
      {source ?? "Saved"}
      {folder ? (
        <>
          {" in the folder "}
          <Link className={LINK_CLASS} search={{ folder: folder.id }} to="/files">
            {folder.name}
          </Link>
        </>
      ) : null}
      .
    </p>
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

export function TextList({ items, title }: { items: string[]; title: string }) {
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

export function DocumentHeading({ children, icon: Icon }: { children: string; icon: LucideIcon }) {
  return (
    <span className="inline-flex min-w-0 items-center gap-2">
      <Icon className="text-muted-foreground size-4 shrink-0" />
      <span className="truncate">{children}</span>
    </span>
  )
}
