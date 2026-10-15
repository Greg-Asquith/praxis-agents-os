// apps/web/src/integrations/meta_ads/components/outcome-table.tsx

import type { ReactNode } from "react"

import { OutcomeSummary } from "@/components/tool-ui/outcome-summary"
import { Badge } from "@/components/ui/badge"
import { DataTable, type DataColumn, type DataRow } from "@/components/ui/data-table"
import { adsManagerObjectUrl } from "@/integrations/meta_ads/lib/ads-manager-link"
import {
  countByKind,
  outcomeKind,
  outcomeLabel,
  outcomeTone,
  type OutcomeKind,
  type OutcomeToken,
} from "@/integrations/meta_ads/lib/outcomes"
import { titleCaseToken } from "@/lib/format"

export type MetaAdsOutcomeRow = DataRow & {
  outcome: OutcomeToken
  details?: string
  errorCode?: string | null
}

const BADGE_VARIANTS = {
  applied: "success",
  failed: "destructive",
  skipped: "secondary",
  unverified: "warning",
} as const

export function MetaAdsOutcomeTable({
  columns,
  rows,
  exportFilename,
  renderCell,
}: {
  columns: DataColumn[]
  rows: MetaAdsOutcomeRow[]
  exportFilename: string
  renderCell?: (column: DataColumn, row: DataRow) => ReactNode | null
}) {
  const tableColumns: DataColumn[] = [
    ...columns,
    { key: "outcome", kind: "status", label: "Outcome" },
  ]
  if (rows.some((row) => Boolean(row.details)))
    tableColumns.push({ key: "details", kind: "text", label: "Details" })
  if (rows.some((row) => row.errorCode))
    tableColumns.push({ key: "errorCode", kind: "badge", label: "Error Code" })
  const tableRows = rows.map((row) => ({
    ...row,
    outcome: outcomeLabel(row.outcome),
    outcomeKind: outcomeKind(row.outcome),
    errorCode: row.errorCode ? titleCaseToken(row.errorCode, row.errorCode) : "",
  }))
  return (
    <DataTable
      columns={tableColumns}
      rows={tableRows}
      exportFilename={exportFilename}
      pageSize={25}
      summary={
        <OutcomeSummary
          items={countByKind(rows).map((item) => ({ ...item, tone: outcomeTone(item.kind) }))}
        />
      }
      renderCell={(column, row) => {
        if (column.key === "outcome") {
          const kind = row["outcomeKind"] as OutcomeKind
          return <Badge variant={BADGE_VARIANTS[kind]}>{String(row["outcome"])}</Badge>
        }
        if (column.key === "errorCode") {
          return typeof row["errorCode"] === "string" && row["errorCode"] ? (
            <Badge variant="outline">{row["errorCode"]}</Badge>
          ) : null
        }
        return renderCell?.(column, row) ?? null
      }}
    />
  )
}

export function MetaAdsFailureTargets({
  description,
  targets,
}: {
  description: string
  targets: readonly string[]
}) {
  return (
    <div className="grid gap-2">
      <p className="text-destructive text-sm">{description}</p>
      {targets.length > 0 ? (
        <div className="flex flex-wrap gap-1">
          {Array.from(new Set(targets)).map((target) => (
            <Badge key={target} variant="secondary">
              {target}
            </Badge>
          ))}
        </div>
      ) : null}
    </div>
  )
}

export function OutcomeLink({ href, children }: { href: string; children: string }) {
  return (
    <a
      className="text-primary w-fit text-xs underline-offset-2 hover:underline"
      href={href}
      rel="noreferrer"
      target="_blank"
    >
      {children}
    </a>
  )
}

/** The links cell for a created or copied ad: Meta's preview and Ads Manager. */
export function AdOutcomeLinks({
  accountId,
  ad,
}: {
  accountId: string
  ad: { adId: string | null; previewUrl: string | null } | undefined
}) {
  if (!ad?.adId) return null
  const manager = adsManagerObjectUrl("ad", accountId, ad.adId)
  return (
    <span className="flex flex-col gap-0.5">
      {ad.previewUrl ? <OutcomeLink href={ad.previewUrl}>Preview on Meta</OutcomeLink> : null}
      {manager ? <OutcomeLink href={manager}>Open in Ads Manager</OutcomeLink> : null}
    </span>
  )
}
