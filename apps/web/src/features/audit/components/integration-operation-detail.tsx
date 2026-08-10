// apps/web/src/features/audit/components/integration-operation-detail.tsx

import { CircleCheckIcon, CircleXIcon, MinusCircleIcon } from "lucide-react"

import { Badge } from "@/components/ui/badge"
import {
  parseIntegrationOperationDetail,
  type AuditDetailValue,
  type OperationChange,
  type OperationDetail,
} from "@/features/audit/operation-detail"
import { titleCaseToken } from "@/lib/format"

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
                <div key={key} className="min-w-0">
                  <dt className="text-muted-foreground text-xs">{titleCaseToken(key, key)}</dt>
                  <dd className="mt-0.5 wrap-break-word">{formatDetailValue(item)}</dd>
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
                    <div className="min-w-0" key={key}>
                      <dt className="text-muted-foreground text-xs">{titleCaseToken(key, key)}</dt>
                      <dd className="mt-0.5 text-sm wrap-break-word">{formatDetailValue(item)}</dd>
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

function formatDetailValue(value: AuditDetailValue | undefined) {
  if (value === undefined || value === null) return "None"
  if (typeof value === "boolean") return value ? "Yes" : "No"
  if (typeof value === "object") return JSON.stringify(value)
  return String(value)
}

function changeKey(change: OperationChange) {
  if (change.external_ref) return change.external_ref
  const fields = Object.entries(change.fields)
    .map(([key, value]) => `${key}=${formatDetailValue(value)}`)
    .join("|")
  return `${change.action}:${change.entity_type}:${fields}`
}
