// apps/web/src/features/audit/components/integration-operation-detail.tsx

import { CircleCheckIcon, CircleXIcon, MinusCircleIcon } from "lucide-react"

import { Badge } from "@/components/ui/badge"
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "@/components/ui/tooltip"
import {
  parseIntegrationOperationDetail,
  type AuditDetailValue,
  type OperationChange,
  type OperationDetail,
} from "@/features/audit/operation-detail"
import { titleCaseToken, truncateText } from "@/lib/format"

const STRUCTURED_VALUE_PREVIEW_LENGTH = 15

export function IntegrationOperationDetail({ value }: { value: unknown }) {
  const detail = parseIntegrationOperationDetail(value)
  if (!detail) {
    return null
  }
  const targetAttributes = Object.entries(detail.target.attributes).filter(
    ([, item]) => item !== null
  )

  return (
    <section className="min-w-0 space-y-5" aria-label="Integration operation outcome">
      <OperationOutcome counts={detail.counts} />

      <div className="space-y-2">
        <SectionLabel>Target</SectionLabel>
        <div className="bg-muted/40 rounded-lg border p-3.5 text-sm">
          <div className="flex min-w-0 items-start justify-between gap-3">
            <div className="min-w-0">
              <p className="font-medium wrap-break-word">
                {detail.target.display_name ?? detail.target.external_id}
              </p>
              <p className="text-muted-foreground mt-0.5 text-xs">
                {titleCaseToken(detail.target.entity_type, detail.target.entity_type)}
              </p>
            </div>
            <Badge variant="outline">ID {detail.target.external_id}</Badge>
          </div>
          {targetAttributes.length > 0 ? (
            <dl className="mt-3 grid gap-2 border-t pt-3 sm:grid-cols-2">
              {targetAttributes.map(([key, item]) => (
                <div
                  key={key}
                  className={isStructuredRecordArray(item) ? "min-w-0 sm:col-span-2" : "min-w-0"}
                >
                  <dt className="text-muted-foreground text-xs">{titleCaseToken(key, key)}</dt>
                  <dd className="mt-0.5 wrap-break-word">
                    <DetailValue value={item} />
                  </dd>
                </div>
              ))}
            </dl>
          ) : null}
        </div>
      </div>

      {detail.changes.length > 0 ? (
        <div className="space-y-2">
          <div className="flex items-center justify-between gap-3">
            <SectionLabel>Changes</SectionLabel>
            <span className="text-muted-foreground text-xs tabular-nums">
              {detail.changes.length} {detail.changes.length === 1 ? "item" : "items"}
            </span>
          </div>
          <div className="max-h-[min(24rem,45dvh)] divide-y overflow-y-auto rounded-lg border">
            {detail.changes.map((change, index) => (
              <article className="min-w-0 space-y-3 p-3.5" key={changeKey(change)}>
                <div className="flex items-center gap-2">
                  <span className="text-muted-foreground text-xs tabular-nums">{index + 1}</span>
                  <Badge variant="success">{titleCaseToken(change.action, change.action)}</Badge>
                  <span className="text-sm font-medium">
                    {titleCaseToken(change.entity_type, change.entity_type)}
                  </span>
                </div>
                <dl className="grid gap-x-4 gap-y-2 sm:grid-cols-2">
                  {Object.entries(change.fields).map(([key, item]) => (
                    <div
                      className={
                        isStructuredRecordArray(item) ? "min-w-0 sm:col-span-2" : "min-w-0"
                      }
                      key={key}
                    >
                      <dt className="text-muted-foreground text-xs">{titleCaseToken(key, key)}</dt>
                      <dd className="mt-0.5 text-sm wrap-break-word">
                        <DetailValue value={item} />
                      </dd>
                    </div>
                  ))}
                </dl>
                {change.external_ref ? (
                  <p className="text-muted-foreground border-t pt-2 font-mono text-[11px] break-all">
                    {change.external_ref}
                  </p>
                ) : null}
              </article>
            ))}
          </div>
        </div>
      ) : null}
    </section>
  )
}

function OperationOutcome({ counts }: { counts: OperationDetail["counts"] }) {
  const hasFailures = counts.failed > 0
  const hasApplied = counts.applied > 0
  const Icon = hasFailures ? CircleXIcon : hasApplied ? CircleCheckIcon : MinusCircleIcon
  const title = hasFailures
    ? `${String(counts.failed)} ${counts.failed === 1 ? "change" : "changes"} failed`
    : hasApplied
      ? `${String(counts.applied)} ${counts.applied === 1 ? "change" : "changes"} applied`
      : "No changes applied"

  return (
    <div className="bg-muted/40 flex items-start gap-3 rounded-lg border p-3.5">
      <div
        className={
          hasFailures
            ? "bg-destructive/10 text-destructive rounded-full p-1.5"
            : "bg-success/10 text-success rounded-full p-1.5"
        }
      >
        <Icon className="size-4" aria-hidden="true" />
      </div>
      <div className="min-w-0">
        <p className="font-medium">{title}</p>
        <p className="text-muted-foreground mt-1 text-xs tabular-nums">
          {counts.applied} applied · {counts.skipped} skipped · {counts.failed} failed
        </p>
      </div>
    </div>
  )
}

function SectionLabel({ children }: { children: string }) {
  return <h3 className="text-muted-foreground text-xs font-medium">{children}</h3>
}

function DetailValue({ value }: { value: AuditDetailValue | undefined }) {
  if (isStructuredRecordArray(value)) {
    return <StructuredRecordTable records={value} />
  }
  return formatDetailValue(value)
}

function StructuredRecordTable({ records }: { records: Record<string, AuditDetailValue>[] }) {
  const columns = recordColumns(records)
  return (
    <TooltipProvider>
      <table aria-label="Structured details" className="w-full table-fixed text-left text-sm">
        <thead>
          <tr className="border-b">
            {columns.map((key) => (
              <th
                className="text-muted-foreground pr-4 pb-2 text-[11px] font-medium last:pr-0"
                key={key}
                scope="col"
              >
                {titleCaseToken(key, key)}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {records.map((record, index) => (
            <tr className="border-b last:border-b-0" key={detailRecordKey(record, index)}>
              {columns.map((key) => (
                <td className="py-3 pr-4 align-top last:pr-0" key={key}>
                  <StructuredRecordValue value={record[key]} />
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </TooltipProvider>
  )
}

function StructuredRecordValue({ value }: { value: AuditDetailValue | undefined }) {
  const formatted = formatDetailValue(value)
  if (formatted.length <= STRUCTURED_VALUE_PREVIEW_LENGTH) {
    return <span className="block max-w-full truncate">{formatted}</span>
  }
  return (
    <Tooltip>
      <TooltipTrigger className="block max-w-full truncate text-left" render={<span />}>
        {truncateText(formatted, STRUCTURED_VALUE_PREVIEW_LENGTH, "…")}
      </TooltipTrigger>
      <TooltipContent className="max-w-[min(48rem,calc(100vw-2rem))] break-all">
        {formatted}
      </TooltipContent>
    </Tooltip>
  )
}

function formatDetailValue(value: AuditDetailValue | undefined): string {
  if (value === undefined || value === null) return "None"
  if (typeof value === "boolean") return value ? "Yes" : "No"
  if (typeof value === "object") return JSON.stringify(value)
  return String(value)
}

function isDetailRecord(value: AuditDetailValue): value is Record<string, AuditDetailValue> {
  return typeof value === "object" && value !== null && !Array.isArray(value)
}

function isStructuredRecordArray(
  value: AuditDetailValue | undefined
): value is Record<string, AuditDetailValue>[] {
  return Array.isArray(value) && value.length > 0 && value.every(isDetailRecord)
}

function recordColumns(records: Record<string, AuditDetailValue>[]): string[] {
  return [...new Set(records.flatMap((record) => Object.keys(record)))]
}

function detailRecordKey(record: Record<string, AuditDetailValue>, index: number): string {
  return `${String(index)}:${JSON.stringify(record)}`
}

function changeKey(change: OperationChange) {
  if (change.external_ref) return change.external_ref
  const fields = Object.entries(change.fields)
    .map(([key, value]) => `${key}=${formatDetailValue(value)}`)
    .join("|")
  return `${change.action}:${change.entity_type}:${fields}`
}
